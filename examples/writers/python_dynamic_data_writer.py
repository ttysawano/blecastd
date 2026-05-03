#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import time


DEFAULT_DYNAMIC_DATA_PATH = "/run/blecastd/dynamic_data.bin"
DEFAULT_INTERVAL_SEC = 2.0
DEFAULT_DYNAMIC_DATA_LEN = 22


def collect_sensor_values() -> dict[str, float | int]:
    return {
        "timestamp": int(time.time()),
        "temperature_c": 23.45,
        "status": 0,
    }


def encode_dynamic_data(values: dict[str, float | int], length: int) -> bytes:
    timestamp = int(values["timestamp"]) & 0xFFFFFFFF
    temp_x100 = int(round(float(values["temperature_c"]) * 100))
    status = int(values["status"]) & 0xFF

    data = struct.pack(">IhB", timestamp, temp_x100, status)
    if len(data) > length:
        return data[:length]
    return data.ljust(length, b"\x00")


def write_dynamic_data_atomic(path: Path, data: bytes, mode: int = 0o664) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")

    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    os.chmod(tmp_path, mode)
    os.replace(tmp_path, path)


def run(interval_sec: float, path: Path, length: int) -> None:
    next_time = time.monotonic()

    while True:
        values = collect_sensor_values()
        dynamic_data = encode_dynamic_data(values, length)
        write_dynamic_data_atomic(path, dynamic_data)
        print(f"[INFO] updated {path} len={len(dynamic_data)} timestamp={values['timestamp']}", flush=True)

        next_time += interval_sec
        sleep_time = next_time - time.monotonic()
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            next_time = time.monotonic()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=DEFAULT_DYNAMIC_DATA_PATH)
    parser.add_argument("--interval-sec", type=float, default=DEFAULT_INTERVAL_SEC)
    parser.add_argument("--length", type=int, default=DEFAULT_DYNAMIC_DATA_LEN)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interval_sec <= 0:
        raise ValueError("--interval-sec must be positive")
    if args.length <= 0:
        raise ValueError("--length must be positive")
    run(interval_sec=args.interval_sec, path=Path(args.path), length=args.length)


if __name__ == "__main__":
    main()
