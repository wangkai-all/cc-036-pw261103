#!/usr/bin/env bash
# 一键启动接收台：生成样例（如需要）+ 启动后端并托管前端构建产物
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements.txt
fi
[ -d samples ] || .venv/bin/python -I scripts/make_samples.py
[ -d frontend/dist ] || (cd frontend && npm install --cache /tmp/npm-cache && npm run build)

export MAIL_INTAKE_HOME="${MAIL_INTAKE_HOME:-$(pwd)/data}"
exec .venv/bin/uvicorn --app-dir backend app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
