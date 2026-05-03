# SPDX-License-Identifier: MIT

"""Dynamic data file helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import grp
import os
import pwd


@dataclass(frozen=True)
class DynamicDataReadResult:
    dynamic_data: bytes
    source_length: int
    warning: str | None = None


def normalize_dynamic_data(data: bytes, *, length: int, fill_byte: bytes) -> DynamicDataReadResult:
    """Pad or truncate dynamic data bytes to the configured length."""

    _validate_length_and_fill_byte(length, fill_byte)
    source_length = len(data)
    if source_length < length:
        return DynamicDataReadResult(
            dynamic_data=data + fill_byte * (length - source_length),
            source_length=source_length,
            warning="dynamic data file is shorter than configured length; padded in memory",
        )
    if source_length > length:
        return DynamicDataReadResult(
            dynamic_data=data[:length],
            source_length=source_length,
            warning="dynamic data file is longer than configured length; truncated in memory",
        )
    return DynamicDataReadResult(dynamic_data=data, source_length=source_length)


def read_dynamic_data_file(path: str | Path, *, length: int, fill_byte: bytes) -> DynamicDataReadResult:
    """Open, read, close, and normalize the dynamic data file."""

    data = Path(path).read_bytes()
    return normalize_dynamic_data(data, length=length, fill_byte=fill_byte)


def initial_dynamic_data(*, length: int, fill_byte: bytes) -> bytes:
    """Return bytes used to initialize a missing dynamic data file."""

    _validate_length_and_fill_byte(length, fill_byte)
    return fill_byte * length


def ensure_dynamic_data_file(
    path: str | Path,
    *,
    length: int,
    fill_byte: bytes,
    mode: int,
    owner: str | None = None,
    group: str | None = None,
) -> bool:
    """Create a missing dynamic data file and return True if it was created."""

    target = Path(path)
    if target.exists():
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(initial_dynamic_data(length=length, fill_byte=fill_byte))
    os.chmod(target, mode)

    uid = -1 if owner is None else pwd.getpwnam(owner).pw_uid
    gid = -1 if group is None else grp.getgrnam(group).gr_gid
    if uid != -1 or gid != -1:
        os.chown(target, uid, gid)
    return True


def _validate_length_and_fill_byte(length: int, fill_byte: bytes) -> None:
    if length < 0:
        raise ValueError("dynamic data length must not be negative")
    if len(fill_byte) != 1:
        raise ValueError("fill_byte must be exactly one byte")
