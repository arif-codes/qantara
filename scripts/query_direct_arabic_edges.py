#!/usr/bin/env python3
"""Print direct Arabic-source edges into selected target languages."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB = Path("data/processed/etymology.sqlite")
DEFAULT_OUTPUT = Path("data/processed/arabic_direct_edges.csv")
DEFAULT_TARGETS = ("English", "Spanish", "Italian")
ARABIC_SOURCE_SQL = """
(
  lower(related_lang) = 'arabic'
  OR lower(related_lang) LIKE '% arabic'
  OR lower(related_lang) LIKE '%-arabic'
)
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--targets", nargs="*", default=list(DEFAULT_TARGETS))
    parser.add_argument("--limit", type=int, default=5000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.db.exists():
        raise SystemExit(f"Database does not exist: {args.db}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in args.targets)
    rows = conn.execute(
        f"""
        SELECT related_lang, related_term, reltype, lang, term
        FROM etymology_edges
        WHERE {ARABIC_SOURCE_SQL}
          AND lang IN ({placeholders})
          AND related_term != ''
        ORDER BY lang, term
        LIMIT ?
        """,
        (*args.targets, args.limit),
    ).fetchall()

    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_lang", "source_term", "reltype", "target_lang", "target_term"])
        for row in rows:
            writer.writerow(
                [
                    row["related_lang"],
                    row["related_term"],
                    row["reltype"],
                    row["lang"],
                    row["term"],
                ]
            )

    print(f"Wrote {len(rows):,} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
