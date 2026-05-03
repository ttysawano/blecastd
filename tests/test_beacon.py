import unittest

from blecastd.beacon import (
    AdvertisingDataError,
    build_custom_manufacturer_advertising_data,
    build_ibeacon_advertising_data,
)


class BeaconTests(unittest.TestCase):
    def test_custom_manufacturer_default_advertising_data(self):
        advertising_data = build_custom_manufacturer_advertising_data(
            company_id=0x1234,
            static_header=b"BC",
            dynamic_data=bytes(22),
        )

        self.assertEqual(len(advertising_data), 31)
        self.assertEqual(advertising_data[:8], bytes.fromhex("0201061bff341242"))
        self.assertEqual(advertising_data[8], 0x43)
        self.assertEqual(advertising_data.hex(), "0201061bff34124243" + "00" * 22)

    def test_custom_manufacturer_rejects_oversized_user_field(self):
        with self.assertRaises(AdvertisingDataError):
            build_custom_manufacturer_advertising_data(
                company_id=0x1234,
                static_header=b"BC",
                dynamic_data=bytes(23),
            )

    def test_ibeacon_advertising_data(self):
        advertising_data = build_ibeacon_advertising_data(
            uuid="12345678-1234-1234-1234-1234567890ab",
            major=1,
            minor=2,
            tx_power=-59,
        )

        self.assertEqual(len(advertising_data), 30)
        self.assertEqual(
            advertising_data.hex(),
            "0201061aff4c000215123456781234123412341234567890ab00010002c5",
        )


if __name__ == "__main__":
    unittest.main()
