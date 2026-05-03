import errno
import subprocess
import struct
import unittest
from unittest.mock import patch

from blecastd.hci import (
    EVT_CMD_COMPLETE,
    EVT_CMD_STATUS,
    HCI_COMMAND_PKT,
    HCI_EVENT_PKT,
    HCI_STATUS_COMMAND_DISALLOWED,
    HCIController,
    HCIError,
    OPCODE_LE_SET_ADVERTISE_ENABLE,
    OPCODE_LE_SET_ADVERTISING_DATA,
    OPCODE_LE_SET_ADVERTISING_PARAMETERS,
    advertising_interval_ms_to_units,
    build_command_response_filter,
    build_le_set_advertise_enable,
    build_le_set_advertising_data,
    build_le_set_advertising_parameters,
    parse_command_result,
    parse_hci_device_name,
)


class FakeSocket:
    def __init__(self):
        self.bind_calls = []
        self.sent_packets = []
        self.timeout = None
        self.closed = False
        self.events = []
        self.setsockopt_error = None
        self.setsockopt_calls = []

    def bind(self, address):
        self.bind_calls.append(address)

    def close(self):
        self.closed = True

    def fileno(self):
        return 1

    def settimeout(self, timeout):
        self.timeout = timeout

    def setsockopt(self, level, optname, value):
        self.setsockopt_calls.append((level, optname, value))
        if self.setsockopt_error is not None:
            raise self.setsockopt_error

    def sendall(self, packet):
        self.sent_packets.append(packet)

    def recv(self, size):
        return self.events.pop(0)


class HCITests(unittest.TestCase):
    def test_parse_hci_device_name(self):
        self.assertEqual(parse_hci_device_name("hci0"), 0)
        self.assertEqual(parse_hci_device_name("hci1"), 1)
        self.assertEqual(parse_hci_device_name("hci12"), 12)

    def test_parse_hci_device_name_rejects_invalid_names(self):
        for device in ("eth0", "bluetooth0", "hci", "hciX"):
            with self.subTest(device=device):
                with self.assertRaises(HCIError):
                    parse_hci_device_name(device)

    def test_open_binds_with_hci_device_id_before_optional_bring_up_failure(self):
        raw_socket = FakeSocket()
        control_socket = FakeSocket()

        with (
            patch("blecastd.hci.platform.system", return_value="Linux"),
            patch("blecastd.hci.socket.AF_BLUETOOTH", 31, create=True),
            patch("blecastd.hci.socket.BTPROTO_HCI", 1, create=True),
            patch("blecastd.hci.socket.socket", side_effect=[raw_socket, control_socket]),
            patch("blecastd.hci.fcntl.ioctl", side_effect=OSError(errno.ENODEV, "No such device")),
            patch(
                "blecastd.hci.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["hciconfig", "hci1", "up"]),
            ),
        ):
            controller = HCIController("hci1")
            controller.open()

        self.assertIs(controller.sock, raw_socket)
        self.assertEqual(raw_socket.bind_calls, [(1,)])

    def test_command_response_filter_layout(self):
        hci_filter = build_command_response_filter(OPCODE_LE_SET_ADVERTISE_ENABLE)

        self.assertEqual(len(hci_filter), 16)
        type_mask, event_mask0, event_mask1, opcode = struct.unpack("<IIIH", hci_filter[:14])
        self.assertEqual(type_mask, 1 << HCI_EVENT_PKT)
        self.assertNotEqual(event_mask0 & (1 << EVT_CMD_COMPLETE), 0)
        self.assertNotEqual(event_mask0 & (1 << EVT_CMD_STATUS), 0)
        self.assertEqual(event_mask1, 0)
        self.assertEqual(opcode, OPCODE_LE_SET_ADVERTISE_ENABLE)

    def test_hci_filter_setup_failure_prevents_command_send(self):
        fake_socket = FakeSocket()
        fake_socket.setsockopt_error = OSError(errno.EINVAL, "Invalid argument")
        packet = build_le_set_advertise_enable(False)
        controller = HCIController("hci0")
        controller.sock = fake_socket

        with self.assertRaises(HCIError):
            controller._send_command(OPCODE_LE_SET_ADVERTISE_ENABLE, packet)

        self.assertEqual(fake_socket.sent_packets, [])

    def test_send_command_ignores_unrelated_events_until_matching_response(self):
        fake_socket = FakeSocket()
        fake_socket.events.extend(
            [
                bytes([0x04, 0x0E, 0x04, 0x01])
                + OPCODE_LE_SET_ADVERTISING_DATA.to_bytes(2, "little")
                + bytes([0x00]),
                bytes([0x04, 0x0E, 0x04, 0x01])
                + OPCODE_LE_SET_ADVERTISE_ENABLE.to_bytes(2, "little")
                + bytes([0x00]),
            ]
        )
        packet = build_le_set_advertise_enable(False)
        controller = HCIController("hci0")
        controller.sock = fake_socket

        result = controller._send_command(OPCODE_LE_SET_ADVERTISE_ENABLE, packet)

        self.assertEqual(result.status, 0)
        self.assertEqual(fake_socket.sent_packets, [packet])

    def test_initial_disable_allows_command_disallowed(self):
        fake_socket = FakeSocket()
        fake_socket.events.append(
            bytes([0x04, 0x0E, 0x04, 0x01])
            + OPCODE_LE_SET_ADVERTISE_ENABLE.to_bytes(2, "little")
            + bytes([HCI_STATUS_COMMAND_DISALLOWED])
        )
        controller = HCIController("hci0")
        controller.sock = fake_socket

        controller.set_advertising_enabled(False, allow_command_disallowed=True)

        self.assertEqual(len(fake_socket.sent_packets), 1)

    def test_advertising_enable_rejects_command_disallowed(self):
        fake_socket = FakeSocket()
        fake_socket.events.append(
            bytes([0x04, 0x0E, 0x04, 0x01])
            + OPCODE_LE_SET_ADVERTISE_ENABLE.to_bytes(2, "little")
            + bytes([HCI_STATUS_COMMAND_DISALLOWED])
        )
        controller = HCIController("hci0")
        controller.sock = fake_socket

        with self.assertRaises(HCIError):
            controller.set_advertising_enabled(True, allow_command_disallowed=True)

    def test_advertising_interval_conversion(self):
        self.assertEqual(advertising_interval_ms_to_units(100), 160)

    def test_set_advertising_parameters_command(self):
        packet = build_le_set_advertising_parameters(100)

        self.assertEqual(packet[0], HCI_COMMAND_PKT)
        self.assertEqual(int.from_bytes(packet[1:3], "little"), OPCODE_LE_SET_ADVERTISING_PARAMETERS)
        self.assertEqual(packet[3], 15)
        self.assertEqual(packet[4:8], bytes.fromhex("a000a000"))
        self.assertEqual(packet[8], 0x00)
        self.assertEqual(packet[-2:], bytes([0x07, 0x00]))

    def test_set_advertising_data_command_pads_to_31_bytes(self):
        packet = build_le_set_advertising_data(bytes.fromhex("020106"))

        self.assertEqual(int.from_bytes(packet[1:3], "little"), OPCODE_LE_SET_ADVERTISING_DATA)
        self.assertEqual(packet[3], 32)
        self.assertEqual(packet[4], 3)
        self.assertEqual(packet[5:8], bytes.fromhex("020106"))
        self.assertEqual(len(packet), 36)

    def test_set_advertise_enable_command(self):
        packet = build_le_set_advertise_enable(True)

        self.assertEqual(int.from_bytes(packet[1:3], "little"), OPCODE_LE_SET_ADVERTISE_ENABLE)
        self.assertEqual(packet[3:], bytes([1, 1]))

    def test_parse_command_complete(self):
        event = (
            bytes([0x04, 0x0E, 0x04, 0x01])
            + OPCODE_LE_SET_ADVERTISING_DATA.to_bytes(2, "little")
            + bytes([0x00])
        )

        result = parse_command_result(event, OPCODE_LE_SET_ADVERTISING_DATA)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, 0)

    def test_parse_command_status(self):
        event = (
            bytes([0x04, 0x0F, 0x04, 0x0C, 0x01])
            + OPCODE_LE_SET_ADVERTISE_ENABLE.to_bytes(2, "little")
        )

        result = parse_command_result(event, OPCODE_LE_SET_ADVERTISE_ENABLE)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, 0x0C)


if __name__ == "__main__":
    unittest.main()
