#!/usr/bin/env python3
"""Download the droher/etymology-db release asset used by Slice 1."""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path


DATASET_URL = (
    "https://github.com/droher/etymology-db/releases/download/"
    "2023-12/etymology.csv.gz"
)
DEFAULT_OUTPUT = Path("data/raw/etymology.csv.gz")


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def download(url: str, output: Path, force: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        print(f"Already exists: {output} ({human_size(output.stat().st_size)})")
        return

    tmp = output.with_suffix(output.suffix + ".part")
    if tmp.exists():
        tmp.unlink()

    print(f"Downloading {url}")
    print(f"Writing to {output}")
    start = time.monotonic()

    with urllib.request.urlopen(url) as response, tmp.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        seen = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            seen += len(chunk)
            if total:
                percent = seen / total * 100
                print(
                    f"\r{human_size(seen)} / {human_size(total)} ({percent:5.1f}%)",
                    end="",
                    flush=True,
                )
        print()

    tmp.replace(output)
    elapsed = max(time.monotonic() - start, 0.001)
    rate = output.stat().st_size / elapsed
    print(f"Done: {human_size(output.stat().st_size)} at {human_size(int(rate))}/s")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DATASET_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    download(args.url, args.output, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

