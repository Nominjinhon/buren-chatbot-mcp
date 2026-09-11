---
description: Spin up and exercise the local dev environment for the buren loan chatbot backend (host Postgres, migrations, seed data, tests, MCP tool checks, real-server smoke test). Use whenever asked to run, test, or verify this project locally.
---

# buren dev loop

This project points at the **host machine's own Postgres** (not a Docker
container) for local dev - this machine already runs Postgres 18 on port
5432. Do not spin up a separate `postgres` container for local iteration.

## 1. One-time host DB setup (human only - needs sudo password)

If the `buren` role / `buren_chatbot` database don't exist yet on the host
Postgres, a human must run this (an agent has no sudo/postgres credentials):

```bash
sudo -u postgres psql -c "CREATE ROLE buren LOGIN PASSWORD 'buren';" \
                       -c "CREATE DATABASE buren_chatbot OWNER buren;"
```

Verify it worked:

```bash
PGPASSWORD=buren psql -h localhost -p 5432 -U buren -d buren_chatbot -c "select 1;"
```

Always export this for every subsequent command in this doc:

```bash
export DATABASE_URL="postgresql+psycopg://buren:buren@localhost:5432/buren_chatbot"
```

(When the app runs *inside a Docker container* instead - the shipped
`docker-compose.yml` - the same host Postgres is reached via
`host.docker.internal` in place of `localhost`, with `extra_hosts:
["host.docker.internal:host-gateway"]` on the `app` service.)

## 2. Install deps, migrate, seed

```bash
uv sync
uv run alembic upgrade head
uv run python -m app.database.seed          # skips if already seeded
uv run python -m app.database.seed --reset  # wipe + reseed with fresh mock data
```

Seed data is idempotent and uses deterministic customer UUIDs (`uuid5` off a
fixed namespace), so IDs are stable across reseeds - handy for repeatable
manual `curl` testing.

## 3. Run the test suite

```bash
uv run pytest tests/ -v
```

All tests run against SQLite in-memory (via `tests/conftest.py`'s `session`
fixture) or fully mocked LLM/MCP clients - none of them need the host
Postgres or a real `MODEL_API_KEY`. Only manual/smoke testing (steps 4-5
below) touches the real DB.

Note: `ChatGoogleGenerativeAI` (Gemini) validates its API key eagerly at
construction, unlike `ChatAnthropic` - so every test that exercises the real
`/chat` route (even ones that never reach the LLM, like a 404-before-agent
case) must override the `get_agent` dependency with a fake, or it'll fail
with a pydantic `ValidationError` instead of the behavior under test.

## 4. Manually test the MCP server's tools

Fastest path - connect in-process, no subprocess needed:

```python
import asyncio
from mcp.client import Client
from app.mcp_servers.server import mcp as server

async def main():
    async with Client(server) as client:
        print([t.name for t in (await client.list_tools()).tools])
        result = await client.call_tool("get_active_loans", {"customer_id": "<uuid>"})
        print(result.is_error, result.structured_content)

asyncio.run(main())
```

To verify the real stdio subprocess path instead (what actually runs in
production), use `StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_servers.server"])`
with `Client(params)`.

Note the structured-content wrapping convention: a tool returning a Pydantic
object (e.g. `DTIResult`, `CustomerProfile`) comes back as that object's
fields directly; a tool returning a list or a bare scalar comes back wrapped
as `{"result": ...}`.

Also note: `mcp_client.py`'s `_server_params` explicitly passes
`env=dict(os.environ)` to the spawned server, because the `mcp` SDK's
default only inherits a restricted safe-list of env vars into a subprocess
(missing `DATABASE_URL`). If you ever see an MCP tool call fail with a DB
connection error inside Docker specifically (but not bare-metal), check this
first - see `AGENTS.md`'s "Key design decisions" for the full story.

## 5. Run the real server end to end

```bash
./run.sh &   # or: uv run uvicorn app.main:app --host 127.0.0.1 --port 8123
sleep 2
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" \
  -d '{"customer_id": "<uuid>", "message": "Миний идэвхтэй зээлүүд юу вэ?"}'
```

Without `MODEL_API_KEY` set, `/chat` will 500 with a clean "API key required
for Gemini Developer API" error - that's expected and confirms the wiring is
correct, not a bug. Kill the server and any leftover MCP subprocess children
when done:

```bash
pkill -f "uvicorn app.main:app"
pkill -f "app.mcp_servers"
```

## 6. Clean up

```bash
find . -name "__pycache__" -exec rm -rf {} +
find . -name ".pytest_cache" -exec rm -rf {} +
```

Nothing to tear down on the DB side - it's the host's persistent Postgres,
not a throwaway container.

**Do not delete `.env` as part of cleanup** unless you created it yourself
purely as scratch for this session and know its contents are disposable. If
the user set it up (e.g. with a real API key), deleting it destroys their
config - back up its content first (or just leave it alone) if you're not
certain who created it or why.
