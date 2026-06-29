#!/usr/bin/env python3
"""Import etymology-db CSV into a local SQLite graph store."""

from __future__ import annotations

import argparse
import csv
import gzip
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path
from typing import Iterable


DEFAULT_INPUT = Path("data/raw/etymology.csv.gz")
DEFAULT_DB = Path("data/processed/etymology.sqlite")
DATASET_LABEL = "droher/etymology-db 2023-12"

CSV_COLUMNS = [
    "term_id",
    "lang",
    "term",
    "reltype",
    "related_term_id",
    "related_lang",
    "related_term",
    "position",
    "group_tag",
    "parent_tag",
    "parent_position",
]


def normalize_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def batched(rows: Iterable[tuple], size: int) -> Iterable[list[tuple]]:
    batch: list[tuple] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def connect(db_path: Path, force: bool) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        if not force:
            raise SystemExit(
                f"Database already exists: {db_path}. Pass --force to rebuild it."
            )
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE etymology_edges (
          id INTEGER PRIMARY KEY,
          term_id TEXT,
          lang TEXT NOT NULL,
          term TEXT NOT NULL,
          term_norm TEXT NOT NULL,
          reltype TEXT NOT NULL,
          related_term_id TEXT,
          related_lang TEXT,
          related_term TEXT,
          related_term_norm TEXT,
          position TEXT,
          group_tag TEXT,
          parent_tag TEXT,
          parent_position TEXT,
          source_dataset TEXT NOT NULL
        );

        CREATE TABLE import_metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )


def iter_rows(csv_path: Path, limit: int | None = None) -> Iterable[tuple]:
    with gzip.open(csv_path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in CSV_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"Missing expected CSV columns: {', '.join(missing)}")

        for idx, row in enumerate(reader, start=1):
            if limit is not None and idx > limit:
                break
            term = row["term"]
            related_term = row.get("related_term") or ""
            yield (
                row.get("term_id") or "",
                row.get("lang") or "",
                term,
                normalize_key(term),
                row.get("reltype") or "",
                row.get("related_term_id") or "",
                row.get("related_lang") or "",
                related_term,
                normalize_key(related_term),
                row.get("position") or "",
                row.get("group_tag") or "",
                row.get("parent_tag") or "",
                row.get("parent_position") or "",
                DATASET_LABEL,
            )


def import_csv(conn: sqlite3.Connection, csv_path: Path, limit: int | None) -> int:
    insert_sql = """
        INSERT INTO etymology_edges (
          term_id, lang, term, term_norm, reltype, related_term_id, related_lang,
          related_term, related_term_norm, position, group_tag, parent_tag,
          parent_position, source_dataset
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    total = 0
    start = time.monotonic()
    for batch in batched(iter_rows(csv_path, limit), 25_000):
        conn.executemany(insert_sql, batch)
        total += len(batch)
        if total % 250_000 == 0:
            elapsed = max(time.monotonic() - start, 0.001)
            print(f"Imported {total:,} rows ({total / elapsed:,.0f} rows/s)")
    conn.commit()
    return total


def create_indexes(conn: sqlite3.Connection) -> None:
    print("Creating indexes")
    conn.executescript(
        """
        CREATE INDEX idx_edges_child
          ON etymology_edges (lang, term_norm);
        CREATE INDEX idx_edges_parent
          ON etymology_edges (related_lang, related_term_norm);
        CREATE INDEX idx_edges_parent_to_child
          ON etymology_edges (related_lang, related_term_norm, lang, term_norm);
        CREATE INDEX idx_edges_source_target
          ON etymology_edges (related_lang, lang, reltype);
        CREATE INDEX idx_edges_reltype
          ON etymology_edges (reltype);
        """
    )
    conn.commit()


def write_metadata(conn: sqlite3.Connection, csv_path: Path, total: int, elapsed: float) -> None:
    metadata = {
        "dataset": DATASET_LABEL,
        "source_file": str(csv_path),
        "source_file_bytes": str(csv_path.stat().st_size),
        "row_count": str(total),
        "import_seconds": f"{elapsed:.3f}",
    }
    conn.executemany(
        "INSERT INTO import_metadata (key, value) VALUES (?, ?)",
        sorted(metadata.items()),
    )
    conn.commit()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.input.exists():
        raise SystemExit(f"Input file does not exist: {args.input}")

    conn = connect(args.db, args.force)
    try:
        create_schema(conn)
        start = time.monotonic()
        total = import_csv(conn, args.input, args.limit)
        create_indexes(conn)
        elapsed = time.monotonic() - start
        write_metadata(conn, args.input, total, elapsed)
        print(f"Imported {total:,} rows into {args.db} in {elapsed:.1f}s")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

