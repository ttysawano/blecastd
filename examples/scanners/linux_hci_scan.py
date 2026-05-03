#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Linux raw Advertising Data inspection helper.

This example delegates capture to btmon, which is the most reliable reference
tool for Milestone 3 validation. It keeps scanner functionality out of the
daemon while giving a repeatable command for inspecting raw HCI traffic.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="hci0")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if shutil.which("btmon") is None:
        raise SystemExit("btmon is required; install BlueZ tools for your distribution")
    subprocess.run(["btmon", "-i", args.device], check=True)


if __name__ == "__main__":
    main()
