#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Start backend:"
echo "  cd ${ROOT_DIR}/backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
echo
echo "Start frontend:"
echo "  cd ${ROOT_DIR}/frontend && npm run dev -- --host 127.0.0.1"
