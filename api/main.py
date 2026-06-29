"""FastAPI entrypoint for the local Qantara prototype."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .graph_store import DEFAULT_TARGETS, GraphStore


ROOT = Path(__file__).resolve().parents[1]
store = GraphStore()

app = FastAPI(
    title="Qantara API",
    description="Deterministic Arabic-source etymology graph API.",
    version="0.2.0",
)
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


def parse_targets(value: str) -> tuple[str, ...]:
    targets = tuple(part.strip() for part in value.split(",") if part.strip())
    return targets or DEFAULT_TARGETS


@app.get("/api/health")
def health() -> dict:
    try:
        return store.health()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/graph")
def graph(
    q: str = Query(..., min_length=1),
    language: str = "English",
    targets: str = ",".join(DEFAULT_TARGETS),
) -> dict:
    try:
        return store.graph_for_query(q, language, parse_targets(targets))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1),
    language: str = "English",
    targets: str = ",".join(DEFAULT_TARGETS),
) -> dict:
    try:
        return store.search(q, language, parse_targets(targets))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/arabic-family/{source_term}")
def arabic_family(
    source_term: str,
    targets: str = ",".join(DEFAULT_TARGETS),
    limit: int = Query(60, ge=1, le=250),
) -> dict:
    try:
        return store.source_family(source_term, parse_targets(targets), limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/paths/{language}/{term}")
def paths(
    language: str,
    term: str,
    max_depth: int = Query(6, ge=1, le=10),
    max_paths: int = Query(5, ge=1, le=25),
) -> dict:
    try:
        return {
            "language": language,
            "term": term,
            "paths": store.find_paths(language, term, max_depth=max_depth, max_paths=max_paths),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/styles.css")
def styles() -> FileResponse:
    return FileResponse(ROOT / "styles.css")


@app.get("/app.js")
def javascript() -> FileResponse:
    return FileResponse(ROOT / "app.js")


@app.get("/data/sugar.js")
def sugar_javascript() -> FileResponse:
    return FileResponse(ROOT / "data" / "sugar.js")


@app.get("/data/sugar.json")
def sugar_json() -> FileResponse:
    return FileResponse(ROOT / "data" / "sugar.json")
