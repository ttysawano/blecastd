# SPDX-License-Identifier: MIT

"""TOML configuration loading and validation for blecastd."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from typing import Any


class ConfigError(ValueError):
    """Raised when configuration is invalid."""


@dataclass(frozen=True)
class BluetoothConfig:
    device: str
    advertising_type: str


@dataclass(frozen=True)
class ServiceConfig:
    update_interval_ms: int
    advertising_interval_ms: int
    trigger_mode: str
    oneshot_duration_ms: int


@dataclass(frozen=True)
class BeaconConfig:
    format: str


@dataclass(frozen=True)
class CustomManufacturerConfig:
    company_id: int


@dataclass(frozen=True)
class UserFieldConfig:
    static_header_hex: str
    static_header_length: int
    static_header: bytes


@dataclass(frozen=True)
class DynamicDataConfig:
    file: Path
    length: int
    fill_byte_hex: str
    fill_byte: bytes
    mode: int
    owner: str
    group: str
    write_method: str


@dataclass(frozen=True)
class IBeaconConfig:
    uuid: str
    major: int
    minor: int
    tx_power: int


@dataclass(frozen=True)
class BlecastdConfig:
    bluetooth: BluetoothConfig
    service: ServiceConfig
    beacon: BeaconConfig
    custom_manufacturer: CustomManufacturerConfig
    user_field: UserFieldConfig
    dynamic_data: DynamicDataConfig
    ibeacon: IBeaconConfig
    warnings: tuple[str, ...] = ()


DEFAULT_CONFIG: dict[str, Any] = {
    "bluetooth": {"device": "hci0", "advertising_type": "non_connectable"},
    "service": {
        "update_interval_ms": 2000,
        "advertising_interval_ms": 100,
        "trigger_mode": "periodic",
        "oneshot_duration_ms": 300,
    },
    "beacon": {"format": "custom_manufacturer"},
    "custom_manufacturer": {"company_id": "0x1234"},
    "user_field": {"static_header_hex": "4243", "static_header_length": 2},
    "dynamic_data": {
        "file": "/run/blecastd/dynamic_data.bin",
        "length": 22,
        "fill_byte_hex": "00",
        "mode": "0664",
        "owner": "root",
        "group": "blecast",
        "write_method": "atomic_replace",
    },
    "ibeacon": {
        "uuid": "12345678-1234-1234-1234-1234567890ab",
        "major": 1,
        "minor": 1,
        "tx_power": -59,
    },
}

VALID_BEACON_FORMATS = {"custom_manufacturer", "ibeacon"}
VALID_ADVERTISING_TYPES = {"connectable", "non_connectable"}
VALID_TRIGGER_MODES = {"periodic", "signal", "both"}
HCI_DEVICE_RE = re.compile(r"^hci[0-9]+$")


def load_config(path: str | Path, *, require_hci_device: bool = False) -> BlecastdConfig:
    """Read TOML configuration, merge defaults, and validate values."""

    config_path = Path(path)
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"configuration file cannot be read: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML parsing failed: {exc}") from exc

    merged = _deep_merge(DEFAULT_CONFIG, raw)
    return build_config(merged, require_hci_device=require_hci_device)


def build_config(raw: dict[str, Any], *, require_hci_device: bool = False) -> BlecastdConfig:
    """Build a typed configuration object from a merged dictionary."""

    warnings: list[str] = []

    bluetooth_device = _require_str(raw, "bluetooth", "device")
    if not HCI_DEVICE_RE.fullmatch(bluetooth_device):
        raise ConfigError("bluetooth.device must be in hciN form")
    if require_hci_device and not Path("/sys/class/bluetooth", bluetooth_device).exists():
        raise ConfigError(f"configured HCI device does not exist: {bluetooth_device}")
    advertising_type = _require_str(raw, "bluetooth", "advertising_type")
    if advertising_type not in VALID_ADVERTISING_TYPES:
        raise ConfigError(f"bluetooth.advertising_type is unknown: {advertising_type}")

    service = raw["service"]
    update_interval_ms = _positive_int(service["update_interval_ms"], "service.update_interval_ms")
    advertising_interval_ms = _positive_int(
        service["advertising_interval_ms"], "service.advertising_interval_ms"
    )
    oneshot_duration_ms = _positive_int(service["oneshot_duration_ms"], "service.oneshot_duration_ms")
    trigger_mode = _as_str(service["trigger_mode"], "service.trigger_mode")
    if trigger_mode not in VALID_TRIGGER_MODES:
        raise ConfigError(f"service.trigger_mode is unknown: {trigger_mode}")

    beacon_format = _require_str(raw, "beacon", "format")
    if beacon_format not in VALID_BEACON_FORMATS:
        raise ConfigError(f"beacon.format is unknown: {beacon_format}")

    company_id = parse_company_id(raw["custom_manufacturer"]["company_id"])
    if company_id == 0x1234:
        warnings.append("default temporary Company Identifier 0x1234 is configured")

    static_header_hex = _require_str(raw, "user_field", "static_header_hex")
    static_header = parse_static_header(static_header_hex)
    static_header_length = _positive_or_zero_int(
        raw["user_field"]["static_header_length"], "user_field.static_header_length"
    )
    if static_header_length != len(static_header):
        raise ConfigError(
            "user_field.static_header_length does not match decoded static_header_hex length"
        )

    dynamic = raw["dynamic_data"]
    dynamic_data_length = _positive_or_zero_int(dynamic["length"], "dynamic_data.length")
    fill_byte_hex = _as_str(dynamic.get("fill_byte_hex", "00"), "dynamic_data.fill_byte_hex")
    fill_byte = parse_fill_byte(fill_byte_hex)
    mode = parse_file_mode(dynamic["mode"])

    if beacon_format == "custom_manufacturer" and static_header_length + dynamic_data_length > 24:
        raise ConfigError("user_field.static_header_length + dynamic_data.length must be <= 24")

    ibeacon = raw["ibeacon"]
    major = _range_int(ibeacon["major"], "ibeacon.major", 0, 0xFFFF)
    minor = _range_int(ibeacon["minor"], "ibeacon.minor", 0, 0xFFFF)
    tx_power = _range_int(ibeacon["tx_power"], "ibeacon.tx_power", -128, 127)

    return BlecastdConfig(
        bluetooth=BluetoothConfig(device=bluetooth_device, advertising_type=advertising_type),
        service=ServiceConfig(
            update_interval_ms=update_interval_ms,
            advertising_interval_ms=advertising_interval_ms,
            trigger_mode=trigger_mode,
            oneshot_duration_ms=oneshot_duration_ms,
        ),
        beacon=BeaconConfig(format=beacon_format),
        custom_manufacturer=CustomManufacturerConfig(company_id=company_id),
        user_field=UserFieldConfig(
            static_header_hex=static_header_hex,
            static_header_length=static_header_length,
            static_header=static_header,
        ),
        dynamic_data=DynamicDataConfig(
            file=Path(_as_str(dynamic["file"], "dynamic_data.file")),
            length=dynamic_data_length,
            fill_byte_hex=fill_byte_hex,
            fill_byte=fill_byte,
            mode=mode,
            owner=_as_str(dynamic["owner"], "dynamic_data.owner"),
            group=_as_str(dynamic["group"], "dynamic_data.group"),
            write_method=_as_str(dynamic["write_method"], "dynamic_data.write_method"),
        ),
        ibeacon=IBeaconConfig(
            uuid=_as_str(ibeacon["uuid"], "ibeacon.uuid"),
            major=major,
            minor=minor,
            tx_power=tx_power,
        ),
        warnings=tuple(warnings),
    )


def parse_company_id(value: Any) -> int:
    if isinstance(value, int):
        company_id = value
    elif isinstance(value, str):
        text = value.strip().lower()
        base = 16 if text.startswith("0x") else 10
        try:
            company_id = int(text, base)
        except ValueError as exc:
            raise ConfigError("custom_manufacturer.company_id is invalid") from exc
    else:
        raise ConfigError("custom_manufacturer.company_id must be a string or integer")

    if not 0 <= company_id <= 0xFFFF:
        raise ConfigError("custom_manufacturer.company_id is outside 0x0000 to 0xffff")
    return company_id


def parse_static_header(static_header_hex: str) -> bytes:
    text = static_header_hex.strip()
    if len(text) % 2 != 0:
        raise ConfigError("user_field.static_header_hex must contain an even number of hex digits")
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise ConfigError("user_field.static_header_hex is invalid hex") from exc


def parse_fill_byte(fill_byte_hex: str | None) -> bytes:
    text = "00" if fill_byte_hex is None else fill_byte_hex.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if len(text) != 2:
        raise ConfigError("dynamic_data.fill_byte_hex must decode to exactly one byte")
    try:
        fill_byte = bytes.fromhex(text)
    except ValueError as exc:
        raise ConfigError("dynamic_data.fill_byte_hex is invalid hex") from exc
    if len(fill_byte) != 1:
        raise ConfigError("dynamic_data.fill_byte_hex must decode to exactly one byte")
    return fill_byte


def parse_file_mode(value: Any) -> int:
    text = _as_str(value, "dynamic_data.mode")
    try:
        mode = int(text, 8)
    except ValueError as exc:
        raise ConfigError("dynamic_data.mode must be an octal string such as 0664") from exc
    if not 0 <= mode <= 0o7777:
        raise ConfigError("dynamic_data.mode is outside valid file mode range")
    return mode


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            result[key] = _deep_merge(value, overlay.get(key, {}))
        else:
            result[key] = overlay.get(key, value)
    for key, value in overlay.items():
        if key not in result:
            result[key] = value
    return result


def _require_str(raw: dict[str, Any], section: str, key: str) -> str:
    return _as_str(raw[section][key], f"{section}.{key}")


def _as_str(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a string")
    return value


def _positive_int(value: Any, name: str) -> int:
    number = _int(value, name)
    if number <= 0:
        raise ConfigError(f"{name} must be positive")
    return number


def _positive_or_zero_int(value: Any, name: str) -> int:
    number = _int(value, name)
    if number < 0:
        raise ConfigError(f"{name} must not be negative")
    return number


def _range_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    number = _int(value, name)
    if not minimum <= number <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return number


def _int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer")
    return value
