# SPDX-License-Identifier: MIT

"""Raw Linux HCI advertising control."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import fcntl
import logging
import platform
import re
import socket
import struct
import subprocess
import time


LOG = logging.getLogger(__name__)

HCI_DEVICE_RE = re.compile(r"^hci([0-9]+)$")

HCI_COMMAND_PKT = 0x01
HCI_EVENT_PKT = 0x04
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F
HCI_STATUS_COMMAND_DISALLOWED = 0x0C

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


def parse_hci_device_name(device: str) -> int:
    match = HCI_DEVICE_RE.fullmatch(device)
    if match is None:
        raise HCIError(f"invalid HCI device name: {device}")
    return int(match.group(1))


def device_name_to_id(device: str) -> int:
    return parse_hci_device_name(device)


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


def build_command_response_filter(opcode: int) -> bytes:
    type_mask = 1 << HCI_EVENT_PKT
    event_mask0 = 0
    event_mask1 = 0
    for event_code in (EVT_CMD_COMPLETE, EVT_CMD_STATUS):
        if event_code < 32:
            event_mask0 |= 1 << event_code
        else:
            event_mask1 |= 1 << (event_code - 32)
    return struct.pack("<IIIHxx", type_mask, event_mask0, event_mask1, opcode)


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

        raw_sock = socket.socket(af_bluetooth, socket.SOCK_RAW, btproto_hci)
        raw_sock.settimeout(self.timeout_sec)
        LOG.debug("binding raw HCI socket for %s with dev_id=%d", self.device, self.dev_id)
        raw_sock.bind((self.dev_id,))
        self.sock = raw_sock
        self._bring_up_if_needed(af_bluetooth, btproto_hci)
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

    def _bring_up_if_needed(self, af_bluetooth: int, btproto_hci: int) -> None:
        control_sock = socket.socket(af_bluetooth, socket.SOCK_RAW, btproto_hci)
        try:
            try:
                fcntl.ioctl(control_sock.fileno(), HCIDEVUP, struct.pack("I", self.dev_id))
                return
            except OSError as exc:
                if exc.errno in (errno.EALREADY, errno.EBUSY):
                    return
                LOG.warning("failed to bring up %s with HCI ioctl: %s", self.device, exc)
        finally:
            control_sock.close()

        try:
            subprocess.run(
                ["hciconfig", self.device, "up"],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            LOG.warning("hciconfig is unavailable; continuing with bound raw HCI device %s", self.device)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            LOG.warning("failed to bring up %s with hciconfig: %s", self.device, detail)
        except OSError as exc:
            LOG.warning("failed to run hciconfig for %s: %s", self.device, exc)

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

    def set_advertising_enabled(self, enabled: bool, *, allow_command_disallowed: bool = False) -> None:
        result = self._send_command(OPCODE_LE_SET_ADVERTISE_ENABLE, build_le_set_advertise_enable(enabled))
        if result.status == 0:
            return
        if not enabled and allow_command_disallowed and result.status == HCI_STATUS_COMMAND_DISALLOWED:
            LOG.info("advertising was already disabled on %s", self.device)
            return
        raise HCIError(
            f"HCI command 0x{OPCODE_LE_SET_ADVERTISE_ENABLE:04x} failed with status 0x{result.status:02x}"
        )

    def _send_command_and_check(self, opcode: int, packet: bytes) -> None:
        result = self._send_command(opcode, packet)
        if result.status != 0:
            raise HCIError(f"HCI command 0x{opcode:04x} failed with status 0x{result.status:02x}")

    def _send_command(self, opcode: int, packet: bytes) -> HCICommandResult:
        if self.sock is None:
            raise HCIError("HCI device is not open")

        self._set_command_event_filter(opcode)
        LOG.debug("sending HCI command 0x%04x to %s", opcode, self.device)
        self.sock.sendall(packet)
        deadline = time.monotonic() + self.timeout_sec
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HCIError(
                    f"timed out waiting for Command Complete or Command Status for HCI command 0x{opcode:04x}"
                )
            self.sock.settimeout(remaining)
            try:
                event = self.sock.recv(260)
            except TimeoutError as exc:
                raise HCIError(
                    f"timed out waiting for Command Complete or Command Status for HCI command 0x{opcode:04x}"
                ) from exc
            result = parse_command_result(event, opcode)
            if result is not None:
                return result

    def _set_command_event_filter(self, opcode: int) -> None:
        if self.sock is None:
            raise HCIError("HCI device is not open")

        hci_filter = build_command_response_filter(opcode)
        level = getattr(socket, "SOL_HCI", SOL_HCI)
        LOG.debug(
            "setting raw HCI command response filter for opcode 0x%04x on %s level=%d optname=%d length=%d",
            opcode,
            self.device,
            level,
            HCI_FILTER,
            len(hci_filter),
        )
        try:
            self.sock.setsockopt(level, HCI_FILTER, hci_filter)
        except OSError as exc:
            raise HCIError(f"failed to set raw HCI command response filter for opcode 0x{opcode:04x}: {exc}") from exc


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
