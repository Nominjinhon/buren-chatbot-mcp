# AGENTS.md

Instructions and context for any AI coding agent working in this repo
(Claude Code, Codex, Cursor, etc.). Claude Code specifically also has a
`.claude/skills/dev-loop/SKILL.md` skill that operationalizes the "Local dev
workflow" section below - other tools should just follow this file directly.

## What this is

A backend for a bank loan information chatbot: FastAPI + a LangGraph agent
that answers customer questions about loan status by calling an MCP
(Model Context Protocol) server, which reads mock data from Postgres. No
real auth, no real banking APIs, no external LLM calls except Google Gemini.
See the original spec context in conversation history / project docs for
the full requirements; this file captures decisions and gotchas that aren't
obvious from reading the code alone.

Note: the original spec called for Anthropic/Claude as the LLM provider;
a later explicit user request switched this to Gemini (`langchain-google-genai`)
and renamed the config env vars from `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` to
the provider-agnostic `MODEL_API_KEY`/`MODEL`. If you're looking for why the
naming is generic rather than Gemini-specific, that's why - swapping provider
again later should only need touching `agent/graph.py`'s `get_default_llm()`.

Note: the original spec/design called for three separate MCP servers (loan
data, financial analytics, customer profile) as three separate stdio
subprocesses; a later explicit user request consolidated them into one file,
`app/mcp_servers/server.py`, run as a single stdio subprocess exposing all
tools. `services/mcp_client.py` and `agent/nodes.py` were simplified to
match - there's no more per-tool "which server does this belong to" routing
(`ServerKey`/dispatch table), since there's only one server to route to.
If you're looking for why `mcp_client.py`'s `all_tools()`/`call_tool()`
don't take a server key, that's why.

Note: a Gmail draft-creation tool (a fourth MCP server, then folded into the
consolidated one above) was built and then fully removed per explicit user
request - along with the `customers.email` column that existed only to
support it. If you find stray references to it in old context/history,
there's no Gmail integration in this codebase anymore.

## Tech stack & versions (read before assuming an old API)

- Python 3.11+, `uv` for dependency management (`pyproject.toml` + `uv.lock`).
- FastAPI, SQLAlchemy 2.0 async + Alembic, Postgres, Pydantic v2.
- LangGraph + LangChain + `langchain-google-genai` (Gemini) for the agent.
- The official `mcp` Python SDK, **version 2.1.1** - a much newer major
  rewrite than most training data reflects. `FastMCP` was renamed to
  `MCPServer` and moved to `mcp.server.mcpserver` (import it via
  `from mcp.server import MCPServer`). Verified legitimate via the package's
  own METADATA (maintained by `modelcontextprotocol/python-sdk`, Anthropic
  staff listed as maintainers) - not a supply-chain issue, just newer.
- `langgraph` 1.2.x and `langchain-core` 1.6.x are also newer major versions
  than commonly-expected. Core APIs used here (`StateGraph`, `add_node`,
  `add_conditional_edges`, `END`, `ChatGoogleGenerativeAI.with_structured_output`)
  were verified against the installed source before use - if something
  doesn't behave as expected, check the installed version's actual source
  under `.venv/lib/*/site-packages/` rather than assuming.
- `langchain-google-genai` is at **4.4.0** (uses the consolidated `google-genai`
  SDK, not the legacy `google-ai-generativelanguage` one). Unlike
  `ChatAnthropic`, **`ChatGoogleGenerativeAI` validates the API key eagerly at
  construction time**, not just when the model is actually invoked - a route
  dependency that builds the agent graph (and therefore the LLM client) will
  raise immediately if `MODEL_API_KEY` is empty, even for a request path that
  never ends up calling the LLM (e.g. a 404 before the agent runs). Tests must
  override `get_agent` even on paths that don't need a real LLM response - see
  `tests/test_chat_api.py`'s `test_chat_unknown_customer_returns_404` and
  `test_chat_invalid_body_returns_422` for the pattern (a real bug here: an
  earlier version of the 404 test declared the `override_agent` fixture but
  forgot to call it, which only surfaced as a failure after this provider
  switch, since `ChatAnthropic` tolerated an empty key at construction time).

## Repo layout

```
app/
├── agent/          # LangGraph: state.py, prompts.py, nodes.py, graph.py
├── api/            # FastAPI routes + deps (DB session, compiled agent)
├── services/       # loan_service, analytics_service (deterministic!), mcp_client
├── mcp_servers/    # 1 read-only MCP server (server.py), stdio transport
├── config/         # Pydantic Settings
├── database/       # SQLAlchemy models, async session, seed.py
├── schemas/        # Pydantic v2 request/response/domain schemas
├── ui.py           # Gradio manual-test UI, mounted onto the FastAPI app at /ui
└── main.py         # FastAPI entrypoint + lifespan (starts/stops MCP clients)
tests/               # pytest + pytest-asyncio, all offline (no real DB/LLM needed)
alembic/             # async-aware env.py, migrations
```

## Key design decisions (non-obvious from code alone)

- **DTI is never LLM-computed.** `analytics_service.calculate_dti` does plain
  arithmetic; the agent only narrates its output. `generate_response`'s system
  prompt explicitly forbids the LLM from computing or altering any number.
- **The disclaimer sentence lives inside the response-generation prompt**
  (`agent/prompts.py`'s `RESPONSE_SYSTEM_PROMPT`), not appended via string
  concatenation after generation - so it can be reworded without touching
  node logic. This was an explicit spec requirement.
- **The `status` field itself has three mutually exclusive values**
  (`active`/`overdue`/`closed`) - a loan is always exactly one of them, and
  `calculate_dti`'s debt sum still queries `status IN (active, overdue)`
  directly against that field, independent of the tool below.
- **`get_active_loans`/`loan_service.get_active_loans` groups `active` and
  `overdue` together** (excludes only `closed`), per a later explicit user
  request - overdue loans are still open/owed, so a customer reasonably
  expects to see them when asking about their current loans. This
  *supersedes* an earlier, stricter version of this same function that
  matched only `status == 'active'`, reasoned from the DTI formula's wording
  ("active **+** overdue loans" only makes sense if the two are disjoint
  *inputs to that sum*) - that reasoning was about the debt-sum query, not
  about what "the customer's active loans" should mean when listing loans,
  and didn't actually hold once someone asked for the latter directly.
- **`LOAN_DETAIL` intent has no `loan_id` in the API request** (`ChatRequest`
  only has `customer_id` + `message`). The classification step extracts an
  optional `loan_type_hint` (e.g. "mortgage", "car") from the natural-language
  message in the same structured-output call as intent+language, and
  `call_tools` deterministically filters the customer's active loans by that
  hint (falls back to the full list if no match). This is a reasonable
  interpretation of an underspecified area, not something the spec dictated.
- **SQLAlchemy `Enum` gotcha**: without `values_callable=lambda e: [m.value
  for m in e]`, SQLAlchemy stores enum **names** (`ACTIVE`) not `.value`
  (`active`). All enum columns in `database/models.py` set this explicitly -
  don't remove it.
- **Postgres enum types aren't dropped by `drop_table`.** The initial Alembic
  migration's `downgrade()` explicitly drops the `loan_type`/`loan_status`
  enum types after dropping tables, or a downgrade→upgrade cycle fails with
  `DuplicateObject`.
- **Seed data sizes loans off each customer's income**, not fixed absolute
  ranges - `LOAN_INCOME_FRACTION_RANGE` in `database/seed.py` picks a target
  monthly payment as a fraction of income, then backs out the principal via
  the amortization formula. An earlier version used fixed absolute principal
  ranges per loan type and produced customers with DTI ratios of 300-600%
  (a mortgage payment bigger than their whole income) - caught by actually
  running `calculate_dti` against seeded data, not just eyeballing the seed
  script. If you touch loan-sizing logic, re-verify DTI stays in a plausible
  band (roughly 5-90%) across all 5 seeded customers.
- **MCP structured-content wrapping convention**: a tool returning a single
  Pydantic object (`DTIResult`, `CustomerProfile`, a single `Loan`) comes back
  as that object's fields directly; a tool returning a list or a bare scalar
  comes back wrapped as `{"result": ...}`. `services/mcp_client.py` and
  `agent/nodes.py`'s `_unwrap_list` account for this - don't assume every
  tool result needs unwrapping.
- **`services/mcp_client.py` keeps one persistent stdio connection to the
  server** for the process's lifetime (opened in `main.py`'s lifespan), not a
  fresh subprocess per call - much lower latency, especially for
  `GENERAL_SUMMARY` which fans out to several tool calls over that one
  connection.
- **Testing `classify_intent` needs a hand-rolled fake**, not LangChain's
  built-in fake chat models: it calls `llm.with_structured_output(...)`,
  which requires real tool-calling support the built-in fakes don't
  implement. See `FakeStructuredLLM`/`TwoStepFakeLLM` in
  `tests/test_agent_graph.py` (reused by `tests/test_chat_api.py`).
  `generate_response`'s plain-text path works fine with the real
  `FakeListChatModel`.
- **MCP stdio subprocesses don't inherit the full parent environment** - the
  `mcp` SDK only passes a restricted safe-list of env vars into a spawned
  server subprocess by default (a security default for *untrusted* servers).
  Since our MCP server is our own code, `mcp_client.py`'s
  `_server_params` explicitly passes `env=dict(os.environ)`. Without this,
  the server subprocess silently fell back to `settings.py`'s hardcoded
  default DB URL (`localhost:5432`) instead of the real `DATABASE_URL` -
  which happened to still work in every bare-metal/host test (the fallback
  coincidentally matched reality there) but broke inside Docker, where
  `localhost` inside the container isn't the host running Postgres. This bug
  was latent through stages 4-7 and only surfaced once a real `MODEL_API_KEY`
  let `classify_intent` succeed for the first time, letting `call_tools`
  actually reach the MCP server. See `tests/test_mcp_client.py`.
- **`ChatGoogleGenerativeAI`'s message `.content` is a list of content
  blocks**, not a plain string - `[{"type": "text", "text": "...", "extras":
  {"signature": "..."}}]` (the `extras.signature` is a grounding/thought
  signature, safe to ignore) - unlike `ChatAnthropic` and the fake test
  models, which return a plain string. `generate_response` normalizes this
  via `nodes._extract_text` before putting it in `ChatResponse.response`
  (a plain `str` field) - without it, Pydantic validation on the response
  fails with `Input should be a valid string`. See
  `tests/test_agent_nodes_helpers.py`.
- **LangSmith tracing is optional, env-var-only, and needs no application
  code** to actually trace runs (LangChain/LangGraph auto-instrument every
  Runnable when `LANGSMITH_TRACING`/`LANGSMITH_API_KEY`/etc. are present in
  `os.environ`). The one piece of real wiring: `pydantic_settings`'
  `env_file=".env"` only populates `Settings`' own declared fields - it never
  mutates the real process environment, so a library that reads `os.environ`
  directly (like `langsmith`) won't see `.env`-only vars on a bare-metal
  `uv run`. `app/config/settings.py` calls `load_dotenv()` (from the existing
  `python-dotenv` dependency) before defining `Settings` to fix this for any
  current or future env vars, not just LangSmith's. `load_dotenv()` never
  overrides a var that's already set, so this is a no-op inside Docker (where
  `docker-compose`'s `env_file:` already sets real container env vars) and a
  no-op if no `.env` file exists at all. Verified for real: ran the agent
  locally with `LANGSMITH_PROJECT=MCP` set, then queried
  `langsmith.Client().list_runs(project_name="MCP")` and confirmed the exact
  run appeared with per-node spans (`classify_intent`, `call_tools`,
  `generate_response`, the underlying `ChatGoogleGenerativeAI` call).
- **The Gradio manual-test UI (`app/ui.py`) is mounted onto the main FastAPI
  app** (`app/main.py`'s `gr.mount_gradio_app(app, build_demo(), path="/ui")`)
  rather than run as a standalone `demo.launch()` script. `mount_gradio_app`
  wraps the existing `lifespan` around Gradio's own, so `mcp_client.start()`/
  `stop()` still run on the one uvicorn event loop for the whole process.
  A standalone Gradio server would need its own copy of that startup/shutdown
  lifecycle, and the MCP client's stdio subprocess/anyio streams, once bound
  to one asyncio event loop, break outright if called from a different one
  ("attached to a different event loop") - so mounting isn't just less code,
  it sidesteps that whole bug class. Visit `/ui` on whatever host/port is
  already serving the FastAPI app (`run.sh`'s port 8000, or Docker's) - no
  separate process or port to run.

## Local dev workflow

**Database: use the host machine's real Postgres, not a Docker container.**
This machine already runs Postgres 18 on port 5432, with a `buren` role and
`buren_chatbot` database already created there. Do not spin up a separate
Postgres container for local dev.

One-time setup on the host, if it's ever missing (needs sudo, run by a human,
not an agent):

```bash
sudo -u postgres psql -c "CREATE ROLE buren LOGIN PASSWORD 'buren';" \
                       -c "CREATE DATABASE buren_chatbot OWNER buren;"
```

Then for every dev/test session:

```bash
export DATABASE_URL="postgresql+psycopg://buren:buren@localhost:5432/buren_chatbot"
uv sync
uv run alembic upgrade head
uv run python -m app.database.seed          # idempotent; --reset to wipe+reseed
uv run pytest tests/ -v                      # tests themselves don't need this DB
```

When the app runs **inside a Docker container** (the shipped
`docker-compose.yml`), the same host Postgres is reached via
`host.docker.internal` instead of `localhost`, with the compose file's `app`
service setting `extra_hosts: ["host.docker.internal:host-gateway"]`:

```
DATABASE_URL=postgresql+psycopg://buren:buren@host.docker.internal:5432/buren_chatbot
```

Running the real server + a smoke test (`run.sh` is the same thing pinned to
port 8000, no migrate/seed step - run those separately first):

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8123 &
curl -s http://127.0.0.1:8123/health
curl -s -X POST http://127.0.0.1:8123/chat -H "Content-Type: application/json" \
  -d '{"customer_id": "<uuid>", "message": "Миний идэвхтэй зээлүүд юу вэ?"}'
```

Or skip curl and use the Gradio UI at `http://127.0.0.1:8123/ui` - pick a
customer from the dropdown, see their full loan info in the sidebar, and
either type a question or click one of the suggested-question buttons.

Without `MODEL_API_KEY` set, `/chat` will 500 with a clean "API key required
for Gemini Developer API" error - that confirms correct wiring, not a bug.

## Testing philosophy

Every test in `tests/` runs fully offline: no real Postgres, no real
Gemini key, no real MCP subprocess. `tests/conftest.py`'s `session`
fixture spins up an in-memory SQLite DB per test; the agent/API tests fake
the LLM and mock `app.agent.nodes.mcp_client`. Manual verification against
the real host Postgres + real MCP subprocess + real server is a separate,
deliberate step (see "Local dev workflow" above) - don't conflate the two.

## Status

All 8 build stages are done and tested: schemas/DB/migrations, seed, services
layer, MCP servers, LangGraph agent, FastAPI `/chat` endpoint, Docker
(`Dockerfile` + `docker-compose.yml`, verified with a real `docker compose up`
against the host Postgres), and `README.md` (written in Mongolian, per
explicit user request - the original spec said README should be in English,
but a direct in-conversation instruction overrides that). `run.sh` runs the
server on port 8000 for local (non-Docker) use.

The system has since been verified fully end-to-end with a **real** Gemini
API key, real Postgres, and real MCP subprocesses inside the actual Docker
container - all six intents (`ACTIVE_LOANS`, `OVERDUE_STATUS`, `DTI_RATIO`,
`LOAN_DETAIL`, `GENERAL_SUMMARY`, `OUT_OF_SCOPE`) tested manually via curl,
correct data, correct language mirroring (Mongolian and English), disclaimer
present. This is what surfaced the two bugs documented above (MCP env
passthrough, Gemini content-block extraction) - both are now fixed and
covered by tests.
