import unittest

from blecastd.hci import (
    HCI_COMMAND_PKT,
    OPCODE_LE_SET_ADVERTISE_ENABLE,
    OPCODE_LE_SET_ADVERTISING_DATA,
    OPCODE_LE_SET_ADVERTISING_PARAMETERS,
    advertising_interval_ms_to_units,
    build_le_set_advertise_enable,
    build_le_set_advertising_data,
    build_le_set_advertising_parameters,
    parse_command_result,
)


class HCITests(unittest.TestCase):
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
