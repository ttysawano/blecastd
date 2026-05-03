#!/usr/bin/env python3
"""Convenience BLE scanner example using Bleak.

Bleak may hide or transform low-level advertising details on some platforms.
Use examples/scanners/linux_hci_scan.py or btmon when raw Advertising Data
inspection matters.
"""

from __future__ import annotations

import argparse
import asyncio


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=10.0)
    return parser.parse_args()


async def scan(duration: float) -> None:
    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise SystemExit("Install bleak to use this example: python3 -m pip install bleak") from exc

    def callback(device, advertising_data) -> None:  # noqa: ANN001
        if advertising_data.manufacturer_data:
            print(f"{device.address} {device.name or ''} {advertising_data.manufacturer_data}")

    scanner = BleakScanner(callback)
    await scanner.start()
    try:
        await asyncio.sleep(duration)
    finally:
        await scanner.stop()


def main() -> None:
    args = parse_args()
    asyncio.run(scan(args.duration))


if __name__ == "__main__":
    main()
