#!/usr/bin/env python3
"""Stand-in for appimageupdatetool's CLI, for tests and demos.

  -j FILE   exit 1 (update available) / 0 (up to date) / 2 (error)
  -O FILE   print progress like the real tool and append to FILE

FAKE_UPDATE picks the outcome: available (default), current, error, fail.
"""
import os
import sys
import time

mode = os.environ.get("FAKE_UPDATE", "available")
args = sys.argv[1:]
path = args[-1] if args else ""
if not os.path.isfile(path):
    print(f"Could not read file: {path}", file=sys.stderr)
    sys.exit(1)

if "-j" in args:
    print("Checking for updates...")
    if mode == "error":
        print("Error checking for changes!", file=sys.stderr)
        sys.exit(2)
    sys.exit(1 if mode in ("available", "fail") else 0)

if "-O" in args:
    out = sys.stdout
    out.write("Checking for updates...\n... done!\n")
    out.flush()
    print("Starting update...", file=sys.stderr, flush=True)
    for pct in range(0, 101, 20):
        out.write(f"\33[2K\r{pct}% done (0.{pct:02d} of 1.00 MiB)...")
        out.flush()
        time.sleep(0.02)
        if mode == "fail" and pct >= 40:
            out.write("\n")
            print("Update failed!", file=sys.stderr, flush=True)
            sys.exit(1)
    out.write("\n")
    with open(path, "a") as f:
        f.write("updated\n")
    print("Signature validation passed", file=sys.stderr)
    print(f"Update successful. Updated existing file {path}", file=sys.stderr, flush=True)
    sys.exit(0)

print("usage: fake_appimageupdatetool.py [-j|-O] FILE", file=sys.stderr)
sys.exit(1)
