# Qantara

A small app for exploring Arabic influence on European languages.

Type a word, and Qantara maps the source-backed etymology path where the local
corpus has one. I started with Arabic into English, Spanish, and Italian because
that is the bit I personally find interesting.

No LLMs here. The app uses `droher/etymology-db`, SQLite, and deterministic graph
traversal. ML/clustering can come later once the graph itself feels useful.

Built by Arif Ahmed:
[GitHub](https://github.com/arif-codes) ·
[LinkedIn](https://uk.linkedin.com/in/arif-ahmed-1205bb191)

## Run locally

```bash
make install
make slice1
make api
```

Then open `http://127.0.0.1:8000`.

`make slice1` downloads the source dataset and builds
`data/processed/etymology.sqlite`. That database is big, so it is ignored by git
on purpose.

## Server deploy

On a server:

```bash
make install
make slice1
HOST=0.0.0.0 PORT=8000 make api
```

Put nginx, Caddy, or whatever in front of it.

## Notes

- Data source: [`droher/etymology-db`](https://github.com/droher/etymology-db)
- Backend: FastAPI over SQLite
- Frontend: plain HTML/CSS/JS for now
- Fonts are bundled locally: Arimo for Latin, Noto Sans Arabic for Arabic
