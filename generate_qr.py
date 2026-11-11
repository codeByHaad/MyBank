#!/usr/bin/env python3
"""
Generate a QR label for a DEMO unit ID.

Usage:  python generate_qr.py DEMO-001
Output: qr_DEMO-001.png

Only put a demo ID in the QR code. Never put donor or patient information in it.
"""
import sys

import qrcode


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python generate_qr.py <DEMO-UNIT-ID>")
    unit_id = sys.argv[1]
    img = qrcode.make(unit_id)
    out = f"qr_{unit_id}.png"
    img.save(out)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
