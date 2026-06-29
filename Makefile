HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: install api download import direct family paths slice1 check

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.txt

api:
	.venv/bin/uvicorn api.main:app --host $(HOST) --port $(PORT)

download:
	python3 scripts/download_etymology_db.py

import:
	python3 scripts/build_sqlite.py --force

direct:
	python3 scripts/query_direct_arabic_edges.py

family:
	python3 scripts/query_arabic_family.py

paths:
	python3 scripts/find_arabic_paths.py

slice1: download import direct family paths

check:
	PYTHONPYCACHEPREFIX=.pycache .venv/bin/python -m py_compile api/*.py scripts/*.py
	node --check app.js
	node --check data/sugar.js
