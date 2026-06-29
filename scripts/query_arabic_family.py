#!/usr/bin/env python3
"""Export direct descendants for one Arabic source term."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("data/processed/etymology.sqlite")
DEFAULT_OUTPUT = Path("data/processed/sugar_source_family.json")
DEFAULT_SOURCE_TERM = "سكر"
DEFAULT_TARGETS = ("English", "Spanish", "Italian")
ARABIC_SOURCE_SQL = """
(
  lower(related_lang) = 'arabic'
  OR lower(related_lang) LIKE '% arabic'
  OR lower(related_lang) LIKE '%-arabic'
)
"""


def normalize_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--source-term", default=DEFAULT_SOURCE_TERM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--targets", nargs="*", default=list(DEFAULT_TARGETS))
    return parser.parse_args(argv)


def query_family(
    conn: sqlite3.Connection,
    source_term: str,
    targets: list[str],
) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in targets)
    source_norm = normalize_key(source_term)
    rows = conn.execute(
        f"""
        SELECT related_lang, related_term, reltype, lang, term
        FROM etymology_edges
        WHERE {ARABIC_SOURCE_SQL}
          AND related_term_norm = ?
          AND lang IN ({placeholders})
          AND related_term != ''
        ORDER BY lang, term, reltype
        """,
        (source_norm, *targets),
    ).fetchall()

    return {
        "source_query": source_term,
        "source_norm": source_norm,
        "targets": targets,
        "descendants": [
            {
                "source_lang": row["related_lang"],
                "source_term": row["related_term"],
                "reltype": row["reltype"],
                "target_lang": row["lang"],
                "target_term": row["term"],
            }
            for row in rows
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.db.exists():
        raise SystemExit(f"Database does not exist: {args.db}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        payload = query_family(conn, args.source_term, args.targets)
    finally:
        conn.close()

    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(payload['descendants']):,} descendants to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
