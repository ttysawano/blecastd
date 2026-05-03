"""Raw Linux HCI advertising control."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import fcntl
import logging
import platform
import socket
import struct
import time


LOG = logging.getLogger(__name__)

HCI_COMMAND_PKT = 0x01
HCI_EVENT_PKT = 0x04
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F

OGF_LE_CTL = 0x08
OCF_LE_SET_ADVERTISING_PARAMETERS = 0x0006
OCF_LE_SET_ADVERTISING_DATA = 0x0008
OCF_LE_SET_ADVERTISE_ENABLE = 0x000A

OPCODE_LE_SET_ADVERTISING_PARAMETERS = (OGF_LE_CTL << 10) | OCF_LE_SET_ADVERTISING_PARAMETERS
OPCODE_LE_SET_ADVERTISING_DATA = (OGF_LE_CTL << 10) | OCF_LE_SET_ADVERTISING_DATA
OPCODE_LE_SET_ADVERTISE_ENABLE = (OGF_LE_CTL << 10) | OCF_LE_SET_ADVERTISE_ENABLE

HCIDEVUP = 0x400448C9
HCI_CHANNEL_RAW = 0
SOL_HCI = 0
HCI_FILTER = 2
ADV_IND = 0x00
OWN_ADDRESS_PUBLIC = 0x00
ALL_ADVERTISING_CHANNELS = 0x07
ALLOW_SCAN_AND_CONNECT_ANY = 0x00
MIN_ADVERTISING_INTERVAL_UNITS = 0x0020
MAX_ADVERTISING_INTERVAL_UNITS = 0x4000


class HCIError(RuntimeError):
    """Raised when HCI control fails."""


@dataclass(frozen=True)
class HCICommandResult:
    opcode: int
    status: int


def device_name_to_id(device: str) -> int:
    if not device.startswith("hci"):
        raise HCIError(f"invalid HCI device name: {device}")
    try:
        return int(device[3:])
    except ValueError as exc:
        raise HCIError(f"invalid HCI device name: {device}") from exc


def advertising_interval_ms_to_units(advertising_interval_ms: int) -> int:
    """Convert milliseconds to BLE advertising interval units of 0.625 ms."""

    units = round(advertising_interval_ms / 0.625)
    if not MIN_ADVERTISING_INTERVAL_UNITS <= units <= MAX_ADVERTISING_INTERVAL_UNITS:
        raise HCIError(
            "advertising_interval_ms must convert to BLE interval units "
            f"{MIN_ADVERTISING_INTERVAL_UNITS}..{MAX_ADVERTISING_INTERVAL_UNITS}"
        )
    return units


def build_hci_command_packet(opcode: int, command_parameters: bytes) -> bytes:
    if len(command_parameters) > 0xFF:
        raise HCIError("HCI command parameters are too long")
    return bytes([HCI_COMMAND_PKT]) + struct.pack("<HB", opcode, len(command_parameters)) + command_parameters


def build_le_set_advertising_parameters(advertising_interval_ms: int) -> bytes:
    interval_units = advertising_interval_ms_to_units(advertising_interval_ms)
    command_parameters = struct.pack(
        "<HHBBB6sBB",
        interval_units,
        interval_units,
        ADV_IND,
        OWN_ADDRESS_PUBLIC,
        OWN_ADDRESS_PUBLIC,
        b"\x00" * 6,
        ALL_ADVERTISING_CHANNELS,
        ALLOW_SCAN_AND_CONNECT_ANY,
    )
    return build_hci_command_packet(OPCODE_LE_SET_ADVERTISING_PARAMETERS, command_parameters)


def build_le_set_advertising_data(advertising_data: bytes) -> bytes:
    if len(advertising_data) > 31:
        raise HCIError("Advertising Data must be 31 bytes or less")
    command_parameters = bytes([len(advertising_data)]) + advertising_data.ljust(31, b"\x00")
    return build_hci_command_packet(OPCODE_LE_SET_ADVERTISING_DATA, command_parameters)


def build_le_set_advertise_enable(enable: bool) -> bytes:
    return build_hci_command_packet(OPCODE_LE_SET_ADVERTISE_ENABLE, bytes([1 if enable else 0]))


class HCIController:
    """Small wrapper around a raw Linux HCI socket."""

    def __init__(self, device: str, *, timeout_sec: float = 2.0) -> None:
        self.device = device
        self.dev_id = device_name_to_id(device)
        self.timeout_sec = timeout_sec
        self.sock: socket.socket | None = None

    def open(self) -> None:
        if platform.system() != "Linux":
            raise HCIError("raw HCI control requires Linux")

        af_bluetooth = getattr(socket, "AF_BLUETOOTH", None)
        btproto_hci = getattr(socket, "BTPROTO_HCI", None)
        if af_bluetooth is None or btproto_hci is None:
            raise HCIError("this Python build does not expose Bluetooth HCI sockets")

        control_sock = socket.socket(af_bluetooth, socket.SOCK_RAW, btproto_hci)
        try:
            try:
                fcntl.ioctl(control_sock.fileno(), HCIDEVUP, struct.pack("I", self.dev_id))
            except OSError as exc:
                if exc.errno not in (errno.EALREADY, errno.EBUSY):
                    raise HCIError(f"failed to bring up {self.device}: {exc}") from exc
        finally:
            control_sock.close()

        raw_sock = socket.socket(af_bluetooth, socket.SOCK_RAW, btproto_hci)
        raw_sock.settimeout(self.timeout_sec)
        try:
            raw_sock.bind((self.dev_id, HCI_CHANNEL_RAW))
        except TypeError:
            raw_sock.bind((self.dev_id,))
        self.sock = raw_sock
        LOG.info("opened raw HCI device %s", self.device)

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None
            LOG.info("closed raw HCI device %s", self.device)

    def __enter__(self) -> "HCIController":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def set_advertising_parameters(self, advertising_interval_ms: int) -> None:
        self._send_command_and_check(
            OPCODE_LE_SET_ADVERTISING_PARAMETERS,
            build_le_set_advertising_parameters(advertising_interval_ms),
        )

    def set_advertising_data(self, advertising_data: bytes) -> None:
        self._send_command_and_check(
            OPCODE_LE_SET_ADVERTISING_DATA,
            build_le_set_advertising_data(advertising_data),
        )

    def set_advertising_enabled(self, enabled: bool) -> None:
        self._send_command_and_check(
            OPCODE_LE_SET_ADVERTISE_ENABLE,
            build_le_set_advertise_enable(enabled),
        )

    def _send_command_and_check(self, opcode: int, packet: bytes) -> None:
        result = self._send_command(opcode, packet)
        if result.status != 0:
            raise HCIError(f"HCI command 0x{opcode:04x} failed with status 0x{result.status:02x}")

    def _send_command(self, opcode: int, packet: bytes) -> HCICommandResult:
        if self.sock is None:
            raise HCIError("HCI device is not open")

        self._set_command_event_filter(opcode)
        self.sock.sendall(packet)
        deadline = time.monotonic() + self.timeout_sec
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HCIError(f"timed out waiting for HCI command 0x{opcode:04x}")
            self.sock.settimeout(remaining)
            event = self.sock.recv(260)
            result = parse_command_result(event, opcode)
            if result is not None:
                return result

    def _set_command_event_filter(self, opcode: int) -> None:
        if self.sock is None:
            raise HCIError("HCI device is not open")

        type_mask = 1 << HCI_EVENT_PKT
        event_mask0 = (1 << EVT_CMD_COMPLETE) | (1 << EVT_CMD_STATUS)
        event_mask1 = 0
        hci_filter = struct.pack("<LLLH", type_mask, event_mask0, event_mask1, opcode)
        self.sock.setsockopt(getattr(socket, "SOL_HCI", SOL_HCI), HCI_FILTER, hci_filter)


def parse_command_result(event: bytes, expected_opcode: int) -> HCICommandResult | None:
    """Parse Command Complete or Command Status for one opcode."""

    if len(event) < 3 or event[0] != HCI_EVENT_PKT:
        return None

    event_code = event[1]
    if event_code == EVT_CMD_COMPLETE:
        if len(event) < 7:
            return None
        opcode = int.from_bytes(event[4:6], "little")
        if opcode != expected_opcode:
            return None
        return HCICommandResult(opcode=opcode, status=event[6])

    if event_code == EVT_CMD_STATUS:
        if len(event) < 7:
            return None
        status = event[3]
        opcode = int.from_bytes(event[5:7], "little")
        if opcode != expected_opcode:
            return None
        return HCICommandResult(opcode=opcode, status=status)

    return None


def open_hci_device(device: str, *, timeout_sec: float = 2.0) -> HCIController:
    controller = HCIController(device, timeout_sec=timeout_sec)
    controller.open()
    return controller
