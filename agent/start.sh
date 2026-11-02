#!/usr/bin/env bash
# Ask SPV - one-click start for Mac/Linux:  bash start.sh
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Open http://localhost:8000  (Ctrl+C to stop)"
.venv/bin/python -m uvicorn main:app --port 8000
