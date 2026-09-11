#!/usr/bin/env bash
set -euo pipefail

python -m app.database.wait_for_db
alembic upgrade head
python -m app.database.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
