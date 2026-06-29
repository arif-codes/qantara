"""SQLite-backed graph queries for the local LanguageGraph API."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "processed" / "etymology.sqlite"
DEFAULT_TARGETS = ("English", "Spanish", "Italian")

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
    "has_root": 8,
    "etymologically_related_to": 9,
    "cognate_of": 10,
}

RELATION_CONFIDENCE = {
    "borrowed_from": 0.96,
    "learned_borrowing_from": 0.9,
    "semi_learned_borrowing_from": 0.88,
    "derived_from": 0.9,
    "inherited_from": 0.82,
    "calque_of": 0.78,
    "semantic_loan_of": 0.76,
    "has_root": 0.72,
    "etymologically_related_to": 0.66,
    "cognate_of": 0.62,
}

ROMANIZATION_HINTS = {
    "سكر": "sukkar",
    "قهوة": "qahwa",
    "صفر": "sifr",
    "زعفران": "za'faran",
    "قطن": "qutn",
    "كحل": "kuhl",
    "كحول": "kuhul",
    "قحول": "quhul",
    "دار": "dar",
    "الصناعة": "al-sina'a",
    "صناعة": "sina'a",
    "دار الصناعة": "dar al-sina'a",
    "طرف الغرب": "tarf al-gharb",
    "المناخ": "al-manakh",
    "مناخ": "manakh",
    "د و ر": "d-w-r",
    "ص ن ع": "s-n-'",
}

ARABIC_LETTER_ROMANIZATION = {
    "ا": "a",
    "أ": "a",
    "إ": "i",
    "آ": "a",
    "ٱ": "a",
    "ء": "'",
    "ؤ": "'",
    "ئ": "'",
    "ب": "b",
    "ة": "a",
    "ت": "t",
    "ث": "th",
    "ج": "j",
    "ح": "h",
    "خ": "kh",
    "د": "d",
    "ذ": "dh",
    "ر": "r",
    "ز": "z",
    "س": "s",
    "ش": "sh",
    "ص": "s",
    "ض": "d",
    "ط": "t",
    "ظ": "z",
    "ع": "'",
    "غ": "gh",
    "ف": "f",
    "ق": "q",
    "ك": "k",
    "ل": "l",
    "م": "m",
    "ن": "n",
    "ه": "h",
    "و": "w",
    "ى": "a",
    "ي": "y",
}

ARABIC_VOWEL_MARKS = {
    "\u064e": "a",
    "\u0650": "i",
    "\u064f": "u",
    "\u064b": "an",
    "\u064d": "in",
    "\u064c": "un",
    "\u0670": "a",
}

IGNORED_ARABIC_MARKS = {
    "\u0640",
    "\u0652",
    "\u0653",
    "\u0654",
    "\u0655",
    "\u200e",
    "\u200f",
}

SUGGESTION_FALLBACK = [
    "sugar",
    "coffee",
    "saffron",
    "zero",
    "alcohol",
    "cotton",
    "arsenal",
    "admiral",
    "algebra",
    "algorithm",
    "alkali",
    "alchemy",
    "almanac",
    "apricot",
    "artichoke",
    "azimuth",
    "cipher",
    "elixir",
    "magazine",
    "tariff",
    "carat",
    "azure",
    "chess",
    "crimson",
    "caliber",
    "gazelle",
    "hazard",
    "lime",
    "orange",
    "safari",
    "talisman",
]

CURATED_WORD_CONFIG = {
    "admiral": {
        "source": "أَمِير الْبَحْر",
        "story": "none",
    },
    "algebra": {
        "source": "جبر",
        "story": "none",
        "targets": {
            "English": "algebra",
            "Spanish": "álgebra",
            "Italian": "algebra",
        },
    },
    "algorithm": {
        "source": "الخَوَارِزْمِيّ",
        "story": "none",
        "targets": {
            "English": "algorithm",
            "Spanish": "algoritmo",
        },
    },
    "alchemy": {
        "source": "كيمياء",
        "story": "none",
        "targets": {
            "English": "alchemy",
            "Spanish": "alquimia",
        },
    },
    "almanac": {
        "source": "الْمَنَاخ",
        "targets": {
            "English": "almanac",
            "Spanish": "almanaque",
        },
    },
    "alkali": {
        "story": "none",
    },
    "cotton": {
        "story": "none",
    },
    "elixir": {
        "story": "none",
    },
    "zero": {
        "source": "صِفْر",
        "targets": {
            "English": "zero",
            "Spanish": "cero",
            "Italian": "zero",
        },
    },
    "cipher": {
        "source": "صِفْر",
        "targets": {
            "English": "cipher",
            "Spanish": "cifra",
            "Italian": "cifra",
        },
    },
}

BRIDGE_LANGUAGE_PRIORITY = {
    "Old French": 0,
    "Middle English": 1,
    "Medieval Latin": 2,
    "Latin": 3,
    "French": 4,
    "Italian": 5,
    "Spanish": 6,
    "Old Spanish": 7,
    "Catalan": 8,
    "Dutch": 9,
    "Turkish": 10,
    "Ottoman Turkish": 11,
    "Persian": 12,
}

WEAK_ROUTE_RELATIONS = {
    "cognate_of",
    "etymologically_related_to",
    "has_root",
    "semantic_loan_of",
    "doublet_with",
}

SIGNAL_DESCRIPTIONS = {
    "Structured relation": (
        "How strong the Wiktionary-derived relation type is. Direct loans such "
        "as borrowed_from score higher than looser links such as cognate_of."
    ),
    "Arabic source family": (
        "Whether the graph found an Arabic or Arabic-variety source term for "
        "the searched word."
    ),
    "Target coverage": (
        "How many of the target languages currently have descendants from the "
        "same Arabic source family."
    ),
    "Deterministic pathing": (
        "This is a transparent SQLite graph traversal."
    ),
}

RELATION_DESCRIPTIONS = {
    "borrowed_from": "A loanword relationship recorded in the source graph.",
    "derived_from": "A broader derivation relationship recorded in the source graph.",
    "inherited_from": "A later form inherited from an earlier stage of the same language family.",
    "etymologically_related_to": "A weaker relation: the terms are etymologically connected, but not necessarily a direct loan.",
    "cognate_of": "A shared-origin relation, usually weaker than direct borrowing.",
    "has_root": "A root relationship, not a direct word-to-word borrowing.",
    "calque_of": "A translated borrowing rather than a phonetic loan.",
    "semantic_loan_of": "A meaning was borrowed, not necessarily the word form.",
}


@dataclass(frozen=True)
class Step:
    child_lang: str
    child_term: str
    relation: str
    parent_lang: str
    parent_term: str
    parent_norm: str


def normalize_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def contains_arabic(value: str) -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", value))


def is_arabic_language(language: str | None) -> bool:
    if not language:
        return False
    normalized = language.casefold().strip()
    return (
        normalized == "arabic"
        or normalized.endswith(" arabic")
        or normalized.endswith("-arabic")
    )


def relation_confidence(relation: str, source_lang: str) -> float:
    base = RELATION_CONFIDENCE.get(relation, 0.58)
    if source_lang != "Arabic" and is_arabic_language(source_lang):
        base -= 0.03
    return round(max(min(base, 0.99), 0.35), 2)


def relation_description(relation: str) -> str:
    return RELATION_DESCRIPTIONS.get(
        relation,
        "A relationship type from the Wiktionary-derived etymology graph.",
    )


def romanization_key(term: str) -> str:
    key = normalize_key(term)
    return "".join(ch for ch in key if unicodedata.category(ch) != "Cf").strip()


def romanize_arabic(term: str) -> str:
    result: list[str] = []

    for char in unicodedata.normalize("NFKD", term):
        if char in IGNORED_ARABIC_MARKS:
            continue
        if char == "\u0651":
            if result and result[-1] not in {" ", "-", "'"}:
                result.append(result[-1])
            continue
        if char in ARABIC_VOWEL_MARKS:
            result.append(ARABIC_VOWEL_MARKS[char])
            continue
        if unicodedata.category(char) in {"Mn", "Cf"}:
            continue
        if char.isspace():
            if result and result[-1] != " ":
                result.append(" ")
            continue
        result.append(ARABIC_LETTER_ROMANIZATION.get(char, char))

    romanized = "".join(result)
    romanized = re.sub(r"\bal", "al", romanized)
    romanized = re.sub(r"\s+", " ", romanized).strip(" -")
    return romanized or term


def romanize_hint(term: str, language: str | None = None) -> str:
    key = romanization_key(term)
    if key in ROMANIZATION_HINTS:
        return ROMANIZATION_HINTS[key]
    if contains_arabic(term) or is_arabic_language(language):
        return romanize_arabic(term)
    return term


def node_id(prefix: str, language: str, term: str) -> str:
    safe = normalize_key(f"{language}-{term}") or "term"
    safe = re.sub(r"[^a-z0-9]+", "-", safe).strip("-")
    return f"{prefix}_{safe[:48]}" if safe else prefix


def graph_key(language: str, term: str) -> tuple[str, str]:
    return (language, normalize_key(term))


def word_config(query: str) -> dict[str, Any]:
    return CURATED_WORD_CONFIG.get(normalize_key(query), {})


def is_root_like_arabic(term: str) -> bool:
    key = romanization_key(term)
    parts = [part for part in key.split() if part]
    return len(parts) >= 2 and all(len(part) <= 1 for part in parts)


class GraphStore:
    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database does not exist: {self.db_path}")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def health(self) -> dict[str, Any]:
        with self.connect() as conn:
            metadata = {
                row["key"]: row["value"]
                for row in conn.execute("SELECT key, value FROM import_metadata")
            }
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "metadata": metadata,
        }

    def find_paths(
        self,
        target_lang: str,
        target_term: str,
        max_depth: int = 6,
        max_paths: int = 5,
        branch_limit: int = 40,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return self._find_paths(
                conn,
                target_lang,
                target_term,
                max_depth,
                max_paths,
                branch_limit,
            )

    def source_family(
        self,
        source_term: str,
        targets: tuple[str, ...] = DEFAULT_TARGETS,
        limit: int = 60,
    ) -> dict[str, Any]:
        source_norm = normalize_key(source_term)
        with self.connect() as conn:
            descendants = self._descendants_for_source_norm(conn, source_norm, targets, limit)
        return {
            "source_query": source_term,
            "source_norm": source_norm,
            "targets": list(targets),
            "descendants": descendants,
        }

    def graph_for_query(
        self,
        query: str,
        language: str = "English",
        targets: tuple[str, ...] = DEFAULT_TARGETS,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("Query cannot be empty")
        config = word_config(query)

        with self.connect() as conn:
            if contains_arabic(query) or is_arabic_language(language):
                source = {
                    "lang": "Arabic",
                    "term": query,
                    "norm": normalize_key(query),
                    "paths": [],
                }
            else:
                paths = self._find_paths(conn, language, query, 6, 8, 45)
                if not paths:
                    return self._empty_graph(query, language, targets)
                source_path = self._select_source_path(paths, config)
                source_node = source_path["source"]
                source = {
                    "lang": source_node["lang"],
                    "term": source_node["term"],
                    "norm": normalize_key(source_node["term"]),
                    "paths": paths,
                }

            descendants = self._descendants_for_source_norm(conn, source["norm"], targets, 80)
            return self._build_graph_payload(query, language, source, descendants, targets, config)

    def search(
        self,
        query: str,
        language: str = "English",
        targets: tuple[str, ...] = DEFAULT_TARGETS,
    ) -> dict[str, Any]:
        graph = self.graph_for_query(query, language, targets)
        return {
            "query": query,
            "language": language,
            "source": graph.get("source"),
            "result_count": len(graph.get("edges", [])),
            "matches": [
                {
                    "language": node["language"],
                    "term": node["term"],
                    "role": node["kind"],
                }
                for node in graph.get("nodes", [])
                if node["kind"] in {"focus", "target"}
            ],
        }

    def _fetch_parent_edges(
        self,
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

    def _find_paths(
        self,
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

            for row in self._fetch_parent_edges(conn, lang, term_norm, branch_limit):
                step = Step(
                    child_lang=row["lang"],
                    child_term=row["term"],
                    relation=row["reltype"],
                    parent_lang=row["related_lang"],
                    parent_term=row["related_term"],
                    parent_norm=row["related_term_norm"],
                )
                next_path = path + [step]

                if is_arabic_language(step.parent_lang):
                    found.append(self._path_to_payload(target_lang, target_term, next_path))
                    if len(found) >= max_paths:
                        break
                    continue

                state = (step.parent_lang, step.parent_norm, len(next_path))
                cycle_key = (step.parent_lang, step.parent_norm)
                previous_nodes = {
                    (item.child_lang, normalize_key(item.child_term)) for item in next_path
                }
                previous_nodes.add((target_lang, normalize_key(target_term)))
                if state not in seen and cycle_key not in previous_nodes:
                    seen.add(state)
                    queue.append((step.parent_lang, step.parent_term, step.parent_norm, next_path))

        return found

    def _descendants_for_source_norm(
        self,
        conn: sqlite3.Connection,
        source_norm: str,
        targets: tuple[str, ...],
        limit: int,
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in targets)
        rows = conn.execute(
            f"""
            SELECT related_lang, related_term, reltype, lang, term
            FROM etymology_edges
            WHERE {ARABIC_SOURCE_SQL}
              AND related_term_norm = ?
              AND lang IN ({placeholders})
              AND related_term != ''
              AND term != ''
            ORDER BY lang, term, reltype
            LIMIT ?
            """,
            (source_norm, *targets, limit),
        ).fetchall()

        by_target: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["lang"], normalize_key(row["term"]))
            candidate = {
                "source_lang": row["related_lang"],
                "source_term": row["related_term"],
                "reltype": row["reltype"],
                "target_lang": row["lang"],
                "target_term": row["term"],
                "confidence": relation_confidence(row["reltype"], row["related_lang"]),
            }
            current = by_target.get(key)
            if current is None or self._edge_rank(candidate) < self._edge_rank(current):
                by_target[key] = candidate

        return sorted(
            by_target.values(),
            key=lambda item: (
                targets.index(item["target_lang"])
                if item["target_lang"] in targets
                else len(targets),
                item["target_term"],
                RELATION_PRIORITY.get(item["reltype"], 99),
            ),
        )

    def _edge_rank(self, edge: dict[str, Any]) -> tuple[int, float]:
        return (RELATION_PRIORITY.get(edge["reltype"], 99), -edge["confidence"])

    def _path_to_payload(
        self,
        target_lang: str,
        target_term: str,
        path: list[Step],
    ) -> dict[str, Any]:
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

    def _build_graph_payload(
        self,
        query: str,
        language: str,
        source: dict[str, Any],
        descendants: list[dict[str, Any]],
        targets: tuple[str, ...],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        routes = self._routes_for_paths(source.get("paths", []))
        story_route = self._select_story_route(routes, config)
        source_id = "source_arabic"
        target_edges = self._select_display_descendants(
            query,
            language,
            descendants,
            targets,
            config,
        )
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        node_ids: dict[tuple[str, str], str] = {}

        def add_node(
            node_id_value: str,
            language_value: str,
            term_value: str,
            kind: str,
            x: float,
            y: float,
            period: str,
        ) -> str:
            key = graph_key(language_value, term_value)
            if key in node_ids:
                return node_ids[key]
            node_ids[key] = node_id_value
            nodes.append(
                {
                    "id": node_id_value,
                    "term": term_value,
                    "roman": romanize_hint(term_value, language_value),
                    "language": language_value,
                    "period": period,
                    "kind": kind,
                    "x": x,
                    "y": y,
                }
            )
            return node_id_value

        add_node(source_id, source["lang"], source["term"], "source", 13, 50, "source")

        story_target_key = (
            graph_key(story_route["target"]["lang"], story_route["target"]["term"])
            if story_route
            else None
        )
        positions = self._target_positions(target_edges, story_target_key)
        story_node_keys = {
            graph_key(node["lang"], node["term"])
            for node in story_route["nodes"][1:]
        } if story_route else set()
        target_ids: dict[tuple[str, str], str] = {}
        for index, descendant in enumerate(target_edges):
            target_id = node_id("target", descendant["target_lang"], descendant["target_term"])
            kind = (
                "focus"
                if descendant["target_lang"] == language
                and normalize_key(descendant["target_term"]) == normalize_key(query)
                else "target"
            )
            x, y = positions[index]
            target_key = graph_key(descendant["target_lang"], descendant["target_term"])
            target_ids[target_key] = add_node(
                target_id,
                descendant["target_lang"],
                descendant["target_term"],
                kind,
                x,
                y,
                "modern",
            )

            if story_target_key == target_key or target_key in story_node_keys:
                continue

            edges.append(
                {
                    "from": source_id,
                    "to": target_id,
                    "relation": descendant["reltype"],
                    "confidence": descendant["confidence"],
                    "evidence": (
                        f"{descendant['source_lang']} {descendant['source_term']} -> "
                        f"{descendant['target_lang']} {descendant['target_term']}"
                    ),
                    "description": (
                        f"{relation_description(descendant['reltype'])} This green edge is "
                        "direct Arabic-source fan-out for the selected source family."
                    ),
                    "kind": "direct",
                }
            )

        if story_route:
            self._add_story_route(
                story_route,
                source,
                source_id,
                target_ids,
                node_ids,
                nodes,
                edges,
            )

        confidence = self._summary_confidence(edges)
        covered_languages = sorted({edge["target_lang"] for edge in target_edges})
        relation_label = self._dominant_relation(target_edges)

        return {
            "query": query,
            "lemma": query,
            "language": language,
            "source": {
                "lang": source["lang"],
                "term": source["term"],
                "norm": source["norm"],
            },
            "summary": {
                "display": query,
                "ipa": "source-backed graph",
                "meaning": "Arabic-source etymology fan-out",
                "confidence": confidence,
                "source": "droher/etymology-db 2023-12 via local SQLite",
            },
            "nodes": nodes,
            "edges": edges,
            "routes": routes,
            "signals": [
                {
                    "label": "Structured relation",
                    "value": relation_label,
                    "weight": 0.42,
                    "description": SIGNAL_DESCRIPTIONS["Structured relation"],
                },
                {
                    "label": "Arabic source family",
                    "value": source["term"],
                    "weight": 0.24,
                    "description": SIGNAL_DESCRIPTIONS["Arabic source family"],
                },
                {
                    "label": "Target coverage",
                    "value": ", ".join(covered_languages) if covered_languages else "none",
                    "weight": min(len(covered_languages) / max(len(targets), 1), 1) * 0.2,
                    "description": SIGNAL_DESCRIPTIONS["Target coverage"],
                },
                {
                    "label": "Deterministic pathing",
                    "value": "SQLite graph traversal",
                    "weight": 0.1,
                    "description": SIGNAL_DESCRIPTIONS["Deterministic pathing"],
                },
            ],
            "suggestions": self._suggestions(query),
        }

    def _empty_graph(
        self,
        query: str,
        language: str,
        targets: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "query": query,
            "lemma": query,
            "language": language,
            "source": None,
            "summary": {
                "display": query,
                "ipa": "no Arabic path found",
                "meaning": "No Arabic-source path found in the local graph",
                "confidence": 0,
                "source": "droher/etymology-db 2023-12 via local SQLite",
            },
            "nodes": [],
            "edges": [],
            "routes": [],
            "signals": [
                {
                    "label": "Structured relation",
                    "value": "not found",
                    "weight": 0,
                    "description": SIGNAL_DESCRIPTIONS["Structured relation"],
                },
                {
                    "label": "Arabic source family",
                    "value": "none",
                    "weight": 0,
                    "description": SIGNAL_DESCRIPTIONS["Arabic source family"],
                },
                {
                    "label": "Target coverage",
                    "value": ", ".join(targets),
                    "weight": 0,
                    "description": SIGNAL_DESCRIPTIONS["Target coverage"],
                },
                {
                    "label": "Deterministic pathing",
                    "value": "no path returned",
                    "weight": 0,
                    "description": SIGNAL_DESCRIPTIONS["Deterministic pathing"],
                },
            ],
            "suggestions": self._suggestions(query),
        }

    def _select_display_descendants(
        self,
        query: str,
        language: str,
        descendants: list[dict[str, Any]],
        targets: tuple[str, ...],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        best_by_language: dict[str, dict[str, Any]] = {}
        query_norm = normalize_key(query)
        target_overrides = {
            lang: normalize_key(term)
            for lang, term in config.get("targets", {}).items()
        }

        for descendant in descendants:
            target_lang = descendant["target_lang"]
            current = best_by_language.get(target_lang)
            is_query_match = (
                target_lang == language and normalize_key(descendant["target_term"]) == query_norm
            )
            preferred_target = target_overrides.get(target_lang)
            is_preferred_target = (
                preferred_target is not None
                and normalize_key(descendant["target_term"]) == preferred_target
            )
            candidate_rank = (
                0 if is_query_match else 1,
                0 if is_preferred_target else 1,
                *self._edge_rank(descendant),
            )
            current_rank = (
                (0 if current and target_lang == language and normalize_key(current["target_term"]) == query_norm else 1),
                (
                    0
                    if current
                    and target_overrides.get(target_lang) is not None
                    and normalize_key(current["target_term"]) == target_overrides[target_lang]
                    else 1
                ),
                *(self._edge_rank(current) if current else (99, 0)),
            )
            if current is None or candidate_rank < current_rank:
                best_by_language[target_lang] = descendant

        return [
            best_by_language[target]
            for target in targets
            if target in best_by_language
        ]

    def _target_positions(
        self,
        descendants: list[dict[str, Any]],
        story_target_key: tuple[str, str] | None = None,
    ) -> list[tuple[int, int]]:
        if len(descendants) == 1:
            only = descendants[0]
            only_key = graph_key(only["target_lang"], only["target_term"])
            if story_target_key and only_key != story_target_key:
                return [(72, 72)]
            return [(78, 50)]
        if len(descendants) == 2:
            if story_target_key:
                return [
                    (78, 50)
                    if graph_key(item["target_lang"], item["target_term"]) == story_target_key
                    else (66, 74)
                    for item in descendants
                ]
            return [(66, 30), (66, 70)]
        if len(descendants) == 3:
            by_lang = {item["target_lang"]: item for item in descendants}
            if {"Spanish", "English", "Italian"}.issubset(by_lang):
                return [
                    (44, 22) if item["target_lang"] == "Spanish"
                    else (80, 50) if item["target_lang"] == "English"
                    else (62, 78)
                    for item in descendants
                ]
        spread = [22, 38, 52, 66, 80]
        return [(72, spread[index % len(spread)]) for index, _ in enumerate(descendants)]

    def _summary_confidence(self, edges: list[dict[str, Any]]) -> float:
        if not edges:
            return 0
        return round(sum(edge["confidence"] for edge in edges) / len(edges), 2)

    def _dominant_relation(self, descendants: list[dict[str, Any]]) -> str:
        if not descendants:
            return "not found"
        return sorted(
            descendants,
            key=lambda item: RELATION_PRIORITY.get(item["reltype"], 99),
        )[0]["reltype"]

    def _suggestions(self, query: str) -> list[str]:
        return SUGGESTION_FALLBACK

    def _select_source_path(
        self,
        paths: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        preferred_source = config.get("source")
        preferred_source_norm = normalize_key(preferred_source) if preferred_source else None

        def rank(path: dict[str, Any]) -> tuple[int, int, int, int, int, float]:
            relations = [edge["reltype"] for edge in path["edges"]]
            source_term = path["source"]["term"]
            return (
                0
                if preferred_source_norm
                and normalize_key(source_term) == preferred_source_norm
                else 1,
                1 if "has_root" in relations else 0,
                1 if is_root_like_arabic(source_term) else 0,
                path["depth"],
                min((RELATION_PRIORITY.get(relation, 99) for relation in relations), default=99),
                -self._route_confidence(path),
            )

        return sorted(paths, key=rank)[0]

    def _select_story_route(
        self,
        routes: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        if config.get("story") == "none":
            return None
        deeper = [
            route
            for route in routes
            if route["depth"] > 1
            and "has_root" not in route["relations"]
        ]
        if not deeper:
            return None
        return sorted(
            deeper,
            key=self._story_route_rank,
        )[0]

    def _story_route_rank(self, route: dict[str, Any]) -> tuple[int, int, int, float, str]:
        bridge_languages = [node["lang"] for node in route["nodes"][1:-1]]
        bridge_rank = min(
            (BRIDGE_LANGUAGE_PRIORITY.get(language, 99) for language in bridge_languages),
            default=99,
        )
        weak_count = sum(
            1 for relation in route["relations"] if relation in WEAK_ROUTE_RELATIONS
        )
        return (
            weak_count,
            bridge_rank,
            route["depth"],
            -route["confidence"],
            route["id"],
        )

    def _add_story_route(
        self,
        route: dict[str, Any],
        primary_source: dict[str, Any],
        primary_source_id: str,
        target_ids: dict[tuple[str, str], str],
        node_ids: dict[tuple[str, str], str],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> None:
        route_nodes = route["nodes"]
        if len(route_nodes) < 2:
            return

        source_y = 50
        target_key = graph_key(route_nodes[-1]["lang"], route_nodes[-1]["term"])
        target_id = target_ids.get(target_key)
        target_node = next((node for node in nodes if node["id"] == target_id), None)
        target_x = float(target_node["x"]) if target_node else 82
        target_y = float(target_node["y"]) if target_node else 50

        route_ids: list[str] = []
        for index, node in enumerate(route_nodes):
            key = graph_key(node["lang"], node["term"])
            if index == 0 and is_arabic_language(node["lang"]):
                route_ids.append(primary_source_id)
                continue
            if index == len(route_nodes) - 1 and key in target_ids:
                route_ids.append(target_ids[key])
                continue

            ratio = index / max(len(route_nodes) - 1, 1)
            x = 13 + (target_x - 13) * ratio
            y = source_y + (target_y - source_y) * ratio
            kind = (
                "source"
                if index == 0
                else "focus"
                if index == len(route_nodes) - 1
                else "bridge"
            )
            period = "source" if kind == "source" else "route"
            new_id = node_id("route", node["lang"], f"{node['term']}-{index}")
            if key in node_ids:
                route_ids.append(node_ids[key])
                continue

            node_ids[key] = new_id
            nodes.append(
                {
                    "id": new_id,
                    "term": node["term"],
                    "roman": node["roman"],
                    "language": node["lang"],
                    "period": period,
                    "kind": kind,
                    "x": round(x, 1),
                    "y": round(y, 1),
                }
            )
            route_ids.append(new_id)

        for index, route_edge in enumerate(route["edges"]):
            if index + 1 >= len(route_ids):
                break
            edges.append(
                {
                    "from": route_ids[index],
                    "to": route_ids[index + 1],
                    "relation": route_edge["reltype"],
                    "confidence": relation_confidence(
                        route_edge["reltype"],
                        route_edge["from"]["lang"],
                    ),
                    "evidence": (
                        f"{route_edge['from']['lang']} {route_edge['from']['term']} -> "
                        f"{route_edge['to']['lang']} {route_edge['to']['term']}"
                    ),
                    "description": (
                        f"{relation_description(route_edge['reltype'])} This blue edge is "
                        "part of the selected deeper path to the searched word."
                    ),
                    "kind": "story",
                }
            )

    def _routes_for_paths(
        self,
        paths: list[dict[str, Any]],
        max_routes: int = 5,
    ) -> list[dict[str, Any]]:
        if not paths:
            return []

        direct = [
            path
            for path in paths
            if path["depth"] == 1
            and path["edges"]
            and path["edges"][0]["reltype"] in {"borrowed_from", "derived_from"}
        ]
        deeper = [path for path in paths if path["depth"] > 1]
        remaining = [path for path in paths if path not in direct and path not in deeper]
        selected = (direct[:1] + deeper + remaining)[:max_routes]

        routes = []
        for index, path in enumerate(selected, start=1):
            route_nodes = []
            for node_index, node in enumerate(path["nodes"]):
                if node_index == 0:
                    kind = "source"
                elif node_index == len(path["nodes"]) - 1:
                    kind = "target"
                else:
                    kind = "bridge"
                route_nodes.append(
                    {
                        "lang": node["lang"],
                        "term": node["term"],
                        "roman": romanize_hint(node["term"], node["lang"]),
                        "kind": kind,
                    }
                )

            relations = [edge["reltype"] for edge in path["edges"]]
            routes.append(
                {
                    "id": f"route_{index}",
                    "label": f"Route {index}",
                    "depth": path["depth"],
                    "source": path["source"],
                    "target": path["target"],
                    "nodes": route_nodes,
                    "edges": path["edges"],
                    "relations": relations,
                    "confidence": self._route_confidence(path),
                }
            )

        return routes

    def _route_confidence(self, path: dict[str, Any]) -> float:
        scores = [
            relation_confidence(edge["reltype"], edge["from"]["lang"])
            for edge in path["edges"]
        ]
        if not scores:
            return 0
        depth_penalty = max(path["depth"] - 1, 0) * 0.03
        return round(max(sum(scores) / len(scores) - depth_penalty, 0.35), 2)
