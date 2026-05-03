# SPDX-License-Identifier: MIT

"""Advertising Data builders for blecastd."""

from __future__ import annotations

from uuid import UUID


LEGACY_ADVERTISING_DATA_MAX_LENGTH = 31
FLAGS_AD_STRUCTURE = bytes([0x02, 0x01, 0x06])
AD_TYPE_MANUFACTURER_SPECIFIC_DATA = 0xFF
IBEACON_COMPANY_ID = 0x004C


class AdvertisingDataError(ValueError):
    """Raised when Advertising Data cannot be built."""


def build_custom_manufacturer_advertising_data(
    *,
    company_id: int,
    static_header: bytes,
    dynamic_data: bytes,
    include_flags: bool = True,
) -> bytes:
    """Build Advertising Data for custom Manufacturer Specific Data mode."""

    if not 0 <= company_id <= 0xFFFF:
        raise AdvertisingDataError("company_id must fit in 16 bits")

    user_field = static_header + dynamic_data
    if include_flags and len(user_field) > 24:
        raise AdvertisingDataError("user field must be <= 24 bytes when Flags are included")

    manufacturer_data = company_id.to_bytes(2, "little") + user_field
    manufacturer_structure = _ad_structure(
        AD_TYPE_MANUFACTURER_SPECIFIC_DATA, manufacturer_data
    )
    advertising_data = (FLAGS_AD_STRUCTURE if include_flags else b"") + manufacturer_structure
    _validate_legacy_length(advertising_data)
    return advertising_data


def build_ibeacon_advertising_data(
    *,
    uuid: str,
    major: int,
    minor: int,
    tx_power: int,
    include_flags: bool = True,
) -> bytes:
    """Build static iBeacon Advertising Data."""

    if not 0 <= major <= 0xFFFF:
        raise AdvertisingDataError("major must fit in 16 bits")
    if not 0 <= minor <= 0xFFFF:
        raise AdvertisingDataError("minor must fit in 16 bits")
    if not -128 <= tx_power <= 127:
        raise AdvertisingDataError("tx_power must fit in signed 8 bits")

    ibeacon_data = (
        IBEACON_COMPANY_ID.to_bytes(2, "little")
        + bytes([0x02, 0x15])
        + UUID(uuid).bytes
        + major.to_bytes(2, "big")
        + minor.to_bytes(2, "big")
        + tx_power.to_bytes(1, "big", signed=True)
    )
    manufacturer_structure = _ad_structure(AD_TYPE_MANUFACTURER_SPECIFIC_DATA, ibeacon_data)
    advertising_data = (FLAGS_AD_STRUCTURE if include_flags else b"") + manufacturer_structure
    _validate_legacy_length(advertising_data)
    return advertising_data


def _ad_structure(ad_type: int, ad_data: bytes) -> bytes:
    length = 1 + len(ad_data)
    if length > 0xFF:
        raise AdvertisingDataError("AD structure length must fit in one byte")
    return bytes([length, ad_type]) + ad_data


def _validate_legacy_length(advertising_data: bytes) -> None:
    if len(advertising_data) > LEGACY_ADVERTISING_DATA_MAX_LENGTH:
        raise AdvertisingDataError("Advertising Data exceeds 31-byte legacy limit")
