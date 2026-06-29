#!/usr/bin/env python3
"""Find target-language terms whose etymology paths reach Arabic."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("data/processed/etymology.sqlite")
DEFAULT_OUTPUT = Path("data/processed/arabic_sample_paths.json")
DEFAULT_REPORT = Path("reports/arabic_influence_summary.json")
DEFAULT_TARGETS = ("English", "Spanish", "Italian")
DEFAULT_SAMPLES = ("sugar", "coffee", "saffron", "zero", "alcohol", "cotton", "arsenal")
ARABIC_SOURCE_SQL = """
(
  lower(related_lang) = 'arabic'
  OR lower(related_lang) LIKE '% arabic'
  OR lower(related_lang) LIKE '%-arabic'
)
"""

RELATION_PRIORITY = {
    "borrowed_from": 1,
    "learned_borrowing_from": 2,
    "semi_learned_borrowing_from": 3,
    "derived_from": 4,
    "inherited_from": 5,
    "calque_of": 6,
    "semantic_loan_of": 7,
    "etymologically_related_to": 8,
    "cognate_of": 9,
}


def normalize_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def is_arabic_language(language: str | None) -> bool:
    if not language:
        return False
    normalized = language.casefold().strip()
    return (
        normalized == "arabic"
        or normalized.endswith(" arabic")
        or normalized.endswith("-arabic")
    )


@dataclass(frozen=True)
class Step:
    child_lang: str
    child_term: str
    relation: str
    parent_lang: str
    parent_term: str


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_parent_edges(
    conn: sqlite3.Connection,
    lang: str,
    term_norm: str,
    branch_limit: int,
) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT lang, term, reltype, related_lang, related_term, related_term_norm
        FROM etymology_edges
        WHERE lang = ?
          AND term_norm = ?
          AND related_lang != ''
          AND related_term != ''
        """,
        (lang, term_norm),
    ).fetchall()
    return sorted(
        rows,
        key=lambda row: (
            RELATION_PRIORITY.get(row["reltype"], 99),
            row["related_lang"],
            row["related_term"],
        ),
    )[:branch_limit]


def find_paths(
    conn: sqlite3.Connection,
    target_lang: str,
    target_term: str,
    max_depth: int,
    max_paths: int,
    branch_limit: int,
) -> list[dict[str, Any]]:
    queue = deque([(target_lang, target_term, normalize_key(target_term), [])])
    seen = {(target_lang, normalize_key(target_term), 0)}
    found: list[dict[str, Any]] = []

    while queue and len(found) < max_paths:
        lang, term, term_norm, path = queue.popleft()
        if len(path) >= max_depth:
            continue

        for row in fetch_parent_edges(conn, lang, term_norm, branch_limit):
            step = Step(
                child_lang=row["lang"],
                child_term=row["term"],
                relation=row["reltype"],
                parent_lang=row["related_lang"],
                parent_term=row["related_term"],
            )
            next_path = path + [step]
            parent_norm = row["related_term_norm"]

            if is_arabic_language(step.parent_lang):
                found.append(path_to_payload(target_lang, target_term, next_path))
                if len(found) >= max_paths:
                    break
                continue

            state = (step.parent_lang, parent_norm, len(next_path))
            cycle_key = (step.parent_lang, parent_norm)
            previous_nodes = {
                (item.child_lang, normalize_key(item.child_term)) for item in next_path
            }
            previous_nodes.add((target_lang, normalize_key(target_term)))
            if state not in seen and cycle_key not in previous_nodes:
                seen.add(state)
                queue.append((step.parent_lang, step.parent_term, parent_norm, next_path))

    return found


def path_to_payload(target_lang: str, target_term: str, path: list[Step]) -> dict[str, Any]:
    # The BFS path is target -> parent -> grandparent. Reverse it for product display.
    nodes = [{"lang": path[-1].parent_lang, "term": path[-1].parent_term}]
    edges = []
    for step in reversed(path):
        edges.append(
            {
                "from": {"lang": step.parent_lang, "term": step.parent_term},
                "to": {"lang": step.child_lang, "term": step.child_term},
                "reltype": step.relation,
            }
        )
        nodes.append({"lang": step.child_lang, "term": step.child_term})

    return {
        "target": {"lang": target_lang, "term": target_term},
        "source": nodes[0],
        "depth": len(path),
        "nodes": nodes,
        "edges": edges,
    }


def direct_counts(conn: sqlite3.Connection, target_langs: tuple[str, ...]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in target_langs)
    rows = conn.execute(
        f"""
        SELECT related_lang AS source_lang, lang AS target_lang, reltype, COUNT(*) AS n
        FROM etymology_edges
        WHERE {ARABIC_SOURCE_SQL}
          AND lang IN ({placeholders})
          AND related_term != ''
        GROUP BY related_lang, lang, reltype
        ORDER BY n DESC
        """,
        target_langs,
    ).fetchall()
    return [dict(row) for row in rows]


def source_language_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT related_lang AS source_lang, COUNT(*) AS n
        FROM etymology_edges
        WHERE {ARABIC_SOURCE_SQL}
          AND related_term != ''
        GROUP BY related_lang
        ORDER BY n DESC
        LIMIT 25
        """
    ).fetchall()
    return [dict(row) for row in rows]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--targets", nargs="*", default=list(DEFAULT_TARGETS))
    parser.add_argument("--samples", nargs="*", default=list(DEFAULT_SAMPLES))
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--max-paths", type=int, default=3)
    parser.add_argument("--branch-limit", type=int, default=40)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(args.db)
    try:
        target_langs = tuple(args.targets)
        sample_results: dict[str, Any] = {}
        for sample in args.samples:
            sample_results[sample] = {
                lang: find_paths(
                    conn,
                    lang,
                    sample,
                    args.max_depth,
                    args.max_paths,
                    args.branch_limit,
                )
                for lang in target_langs
            }

        args.output.write_text(
            json.dumps(sample_results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        report = {
            "targets": list(target_langs),
            "sample_terms": list(args.samples),
            "direct_arabic_edge_counts": direct_counts(conn, target_langs),
            "arabic_source_language_counts": source_language_counts(conn),
            "sample_output": str(args.output),
        }
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"Wrote sample paths: {args.output}")
        print(f"Wrote summary report: {args.report}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
