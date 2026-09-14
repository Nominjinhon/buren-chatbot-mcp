# Зээлийн чатбот (backend)

Банкны зээлийн мэдээлэл лавлах чатботын backend систем. Хэрэглэгч (харилцагч) зээлийн төлөв, хугацаа хэтэрсэн төлбөр, өр-орлогын харьцаа (DTI) зэрэг асуултыг байгалийн хэлээр асуухад, LangGraph агент нь MCP (Model Context Protocol) серверээр дамжуулан бодит (mock) өгөгдлөөс хариулт бүрдүүлдэг.

> **Анхаарах зүйл:** Энэ бол демо/тестийн систем. Жинхэнэ өгөгдлийн сан, гадаад банкны API, нэвтрэлт (authentication) байхгүй. `customer_id` нь хүсэлтийн биед шууд дамждаг (аль хэдийн нэвтэрсэн session-г төлөөлнө).

## Технологийн стек

-   **Python 3.11+**, dependency management: `uv` (`pyproject.toml` + `uv.lock`)
-   **FastAPI** - HTTP API
-   **PostgreSQL** + **SQLAlchemy (async) + Alembic** - өгөгдлийн сан, migration
-   **LangGraph** - агентын orchestration (state graph)
-   **LangChain** + **langchain-google-genai** - prompt, LLM холболт (Gemini)
-   **MCP Python SDK** - зээл/аналитик/харилцагчийн мэдээллийг ил гаргах read-only tool сервер (stdio transport)
-   **Pydantic v2** - өгөгдлийн баталгаажуулалт
-   **Gradio** - гар аргаар туршиж үзэх UI (`/ui`), үндсэн FastAPI дээр mount хийгдсэн
-   **pytest + pytest-asyncio** - тест
-   **Docker + docker-compose** - контейнержүүлэлт

## Төслийн бүтэц

```
app/
├── agent/          # LangGraph: state, prompts, nodes, graph
├── api/            # FastAPI route-ууд, dependency-ууд
├── services/       # loan_service, analytics_service (детерминист!), mcp_client
├── mcp_servers/    # 1 read-only MCP сервер (server.py)
├── config/         # Тохиргоо (Pydantic Settings)
├── database/       # SQLAlchemy models, async session, seed.py
├── schemas/        # Pydantic v2 schema-ууд
├── ui.py           # Gradio UI, /ui дээр FastAPI-д mount хийгдсэн
└── main.py         # FastAPI entrypoint
alembic/             # Migration-ууд
tests/               # pytest тестүүд (бүгд offline ажилладаг)
```

## Өгөгдлийн сан ба сервер архитектур

Энэ төсөл **хостын машин дээрх бодит PostgreSQL**-ийг ашигладаг (тусдаа docker-с удирдагдах `db` сервис биш). `docker-compose.yml` нь зөвхөн `app` (FastAPI) сервисийг агуулж, `host.docker.internal`-ээр дамжуулан хостын Postgres-т холбогддог (`extra_hosts: host.docker.internal:host-gateway`).

Migration нь **Alembic скрипт** хэлбэрээр хийгддэг (`alembic/versions/`), харин mock өгөгдлийг **`python -m app.database.seed` скрипт** үүсгэдэг (Alembic data migration биш) - учир нь энэ нь дахин ажиллуулахад аюулгүй (idempotent) бөгөөд `--reset` флагаар дахин үүсгэх боломжтой.

## Суулгах, тохируулах

### 1. Хостын Postgres дээр role/database үүсгэх (нэг удаа)

```bash
sudo -u postgres psql -c "CREATE ROLE buren LOGIN PASSWORD 'buren';" 
                       -c "CREATE DATABASE buren_chatbot OWNER buren;"
```

### 2. `.env` файл үүсгэх

```bash
cp .env.example .env
```

Дараа нь `.env`-д өөрийн `MODEL_API_KEY`-г (Gemini API key, [Google AI Studio](https://aistudio.google.com/)-с авна) бичнэ үү. Жинхэнэ LLM дуудлага хийхэд шаардлагатай (үгүй бол `/chat` нь "API key required for Gemini Developer API" гэсэн 500 алдаа буцаана - энэ бол зөв ажиллаж байгааг илэрхийлнэ, гэхдээ LLM хариу өгөхгүй).

`.env.example`-ийн агуулга:

```env
DATABASE_URL=postgresql+psycopg://buren:buren@host.docker.internal:5432/buren_chatbot
MODEL=gemini-2.0-flash
MODEL_API_KEY=
MCP_SERVER_PATH=

# Заавал биш: LangSmith трэйсинг
LANGSMITH_TRACING=
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=
```

Локал (Docker-гүй) хөгжүүлэлт хийх үед `DATABASE_URL`-д `host.docker.internal` оронд `localhost`-г ашиглана:

```bash
export DATABASE_URL="postgresql+psycopg://buren:buren@localhost:5432/buren_chatbot"
```

`MCP_SERVER_PATH`-г хоосон орхивол програм өөрөө `python -m app.mcp_servers.server`-ээр серверийг ажиллуулна (custom скрипт зам зааж өгвөл түүнийг ашиглана).

### 3. Хамааралтай сангуудыг суулгах

```bash
uv sync
```

## Migration ажиллуулах

```bash
uv run alembic upgrade head
```

## Mock өгөгдөл үүсгэх (seed)

```bash
uv run python -m app.database.seed          # аль хэдийн байгаа бол алгасна
uv run python -m app.database.seed --reset  # устгаад дахин үүсгэнэ
```

Энэ нь 5 харилцагч (сар бүрийн орлого 800,000-5,000,000₮), тус бүрд нь 5-10 зээл (идэвхтэй/хугацаа хэтэрсэн/хаагдсан холимог), сүүлийн 12 сарын төлбөрийн түүхийн хамт үүсгэдэг. Дор хаяж 2 харилцагчид хугацаа хэтэрсэн зээл байгаа. Харилцагчийн ID-ууд тогтмол (`uuid5` ашигласан тул дахин seed хийхэд ижил хэвээр байна) - гараар тестлэхэд хэрэг болно.

## Тест ажиллуулах

```bash
uv run pytest tests/ -v
```

Бүх тест **offline** ажилладаг - жинхэнэ Postgres, жинхэнэ Gemini key, жинхэнэ MCP дэд процесс хэрэггүй (in-memory SQLite болон fake LLM/mocked MCP client ашигладаг):

-   `test_loan_service.py`, `test_analytics_service.py` - services давхарга (DTI тооцоолол нь LLM-гүйгээр, детерминист код гэдгийг батална)
-   `test_agent_graph.py` - LangGraph граф, fake LLM-тэй тусгаарлагдсан
-   `test_chat_api.py` - `/chat` endpoint, HTTP-ээр бодит хүсэлт илгээж, зөв intent → зөв MCP tool дуудагдсаныг шалгана
-   `test_agent_nodes_helpers.py`, `test_mcp_client.py` - жижиг дотоод функцүүдийн regression тест (LLM-ийн хариу боловсруулалт, MCP дэд процессын орчны хувьсагч дамжуулалт)

## Локал сервер ажиллуулах (Docker-гүйгээр)

```bash
export DATABASE_URL="postgresql+psycopg://buren:buren@localhost:5432/buren_chatbot"
export MODEL_API_KEY="AIza..."
./run.sh   # эсвэл: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`run.sh` нь FastAPI серверийг 8000 порт дээр ажиллуулна (migration/seed хийдэггүй - тэдгээрийг дээрх алхмуудад тусад нь хийсэн байх ёстой).

## Gradio UI

Сервер ажиллаж байхад `http://127.0.0.1:8000/ui` хаягаар нэвтэрч, curl бичихгүйгээр браузер дээрээс шууд туршиж болно:

-   Харилцагч сонгох dropdown - сонгосон харилцагчийн бүх зээлийн мэдээлэл (төрөл, төлөв, үлдэгдэл, сар бүрийн төлбөр), DTI харьцаа хажуу талд шууд харагдана.
-   Чат цонх - чөлөөт бичвэрээр асуулт бичих, эсвэл хажуугийн санал болгож буй асуултууд дээр дарж шууд илгээх боломжтой.

Энэ нь тусдаа процесс биш - `/chat` endpoint-той адил FastAPI апп дотор ажилладаг тул `run.sh`, `docker compose up` ямар ч тохиргоо нэмэлтгүйгээр `/ui`-г мөн ажиллуулна.

## LangSmith трэйсинг (заавал биш)

Агентын граф (intent ангилал, tool дуудлага, LLM хариу) бүрийг [LangSmith](https://smith.langchain.com/)-т трэйс хэлбэрээр илгээж болно - код өөрчлөх шаардлагагүй, зөвхөн `.env`-д доорх орчны хувьсагчдыг тохируулна:

```env
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=<төслийн нэр>
```

`LANGSMITH_TRACING`-г хоосон орхивол (эсвэл огт бичихгүй бол) трэйсинг идэвхгүй байна - LangChain/LangGraph эдгээр хувьсагчийг байхгүй бол ямар ч нэмэлт зан үйлгүй хэвээрээ ажиллана.

**Анхаарах зүйл:** `Settings` (Pydantic Settings) нь `.env`-ээс зөвхөн өөрийн зарласан талбаруудыг (жишээ нь `database_url`, `model`) уншдаг бөгөөд бусад орчны хувьсагчийг жинхэнэ процессын environment рүү экспортлодоггүй. LangSmith SDK нь `os.environ`-оос шууд уншдаг тул `app/config/settings.py`-д `load_dotenv()`-г эхэнд нь дуудсан - ингэснээр `.env` доторх бүх түлхүүр (LangSmith-ийнх байх, эсвэл ирээдүйд нэмэгдэх бусад) жинхэнэ орчны хувьсагч болж, Docker дотор `env_file`-ээр аль хэдийн дамжуулагдсан утгыг дарж бичихгүй.

## Docker Compose-оор ажиллуулах

```bash
cp .env.example .env   # .env дотор MODEL_API_KEY-г бөглөнө
docker compose up --build
```

Контейнер эхлэхэд автоматаар: хостын Postgres-г хүлээх → `alembic upgrade head` → seed скрипт (хоосон бол л ажиллана) → FastAPI сервер асна.

## Гадаад MCP клиентүүдэд зориулсан HTTP endpoint

Дотоод (stdio) MCP серверээс гадна, яг ижил bodит tool-уудыг Railway дээр тусдаа сервис хэлбэрээр HTTP-ээр ил гаргасан байгаа - гадаад MCP клиент (жишээ нь Claude, ChatGPT connector) шууд дуудах боломжтой:

-   **URL:** `https://mcp-min-test-production.up.railway.app/mcp` (streamable HTTP transport)
-   **Health check** (нэвтрэлт шаардахгүй): `https://mcp-min-test-production.up.railway.app/health`
-   **Нэвтрэлт:** `Authorization: Bearer <MCP_HTTP_TOKEN>` толгой заавал шаардлагатай (`/health`-с бусад бүх хүсэлтэд) - токенгүй эсвэл буруу бол `401` буцаана.
-   **Tool/resource/prompt-ууд:** дотоод серверийн (`app/mcp_servers/server.py`) яг адилхан бүрэн жагсаалт - `get_active_loans`, `get_loan_by_id`, `get_overdue_payments`, `calculate_dti`, `get_customer_income`, `get_customer_profile` tool-ууд; `resource://loan-types`, `resource://loan-statuses` эх сурвалж; `summarize_overdue`, `explain_dti` prompt-ууд. Жинхэнэ (Neon) Postgres-тэй холбогддог тул хариу нь бодит өгөгдөл.

> **Нэрийн тухай:** Railway дээрх сервисийн нэр нь `mcp-min-test` (анх Railway deploy/healthcheck-ийг оношлох зорилготой хамгийн бага хамааралтай туршилтын сервер байсан түүхийн улбаатай, `mcp_min/` фолдер), гэхдээ одоо `mcp_min/Dockerfile` нь бусад бодит tool-уудтай ижил `mcp_service/server.py`-г ашигладаг тул бүрэн бодит сервис.

Жишээ (Python, `mcp` SDK-ийн streamable HTTP клиент ашиглан):

```python
import asyncio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "https://mcp-min-test-production.up.railway.app/mcp"
TOKEN = "<MCP_HTTP_TOKEN-ийн утга>"

async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
        async with streamable_http_client(URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "calculate_dti", {"customer_id": "f430bc26-9001-5579-bc8e-7051ff612b88"}
                )
                print(result.content)

asyncio.run(main())
```

## API жишээ

### `GET /health`

```bash
curl http://127.0.0.1:8000/health
```

### `POST /chat`

```bash
curl -X POST http://127.0.0.1:8000/chat 
  -H "Content-Type: application/json" 
  -d '{
    "customer_id": "f430bc26-9001-5579-bc8e-7051ff612b88",
    "message": "Миний DTI хэд вэ?"
  }'
```

Жишээ хариу:

```json
{
  "response": "Таны өр-орлогын харьцаа (DTI) 31.72% байна. Энэ мэдээлэл нь зөвхөн лавлагааны зорилготой бөгөөд зээлийн шийдвэр гаргах үндэслэл болохгүй.",
  "intent": "DTI_RATIO",
  "data": {
    "dti": {
      "customer_id": "f430bc26-9001-5579-bc8e-7051ff612b88",
      "monthly_income": 950000.0,
      "total_monthly_debt_payments": 301339.04,
      "dti_ratio": 31.72
    }
  }
}
```

Дэмжигдсэн асуултын төрлүүд (`intent`):

Intent

Жишээ асуулт

`ACTIVE_LOANS`

"Миний идэвхтэй зээлүүд юу вэ?"

`OVERDUE_STATUS`

"Надад хугацаа хэтэрсэн төлбөр байна уу?"

`DTI_RATIO`

"Миний өр-орлогын харьцаа хэд вэ?"

`LOAN_DETAIL`

"Миний машины зээлийн талаар хэлж өгөөч"

`GENERAL_SUMMARY`

"Миний зээлийн ерөнхий байдлыг хэлж өгөөч"

`OUT_OF_SCOPE`

Зээлтэй холбоогүй асуулт (шинэ зээл авах, цаг агаар г.м)

Хариу нь хэрэглэгчийн бичсэн хэлийг (монгол/англи) тольдоно.

## Чухал зарчмууд

-   **DTI тооцоолол нь бодит код** (`services/analytics_service.py`) хийдэг - LLM тоо тооцдоггүй, зөвхөн бэлэн үр дүнг байгалийн хэлээр илэрхийлдэг.
-   Санхүүгийн бүх хариу нь **сануулга өгүүлбэртэй** дуусна ("Энэ мэдээлэл нь зөвхөн лавлагааны зорилготой...") - энэ нь prompt-д бичигдсэн, кодоор залгаагүй тул хожим засварлахад хялбар.
-   MCP сервер **зөвхөн унших** (read-only) - write/update/delete tool байхгүй.
-   Бүх мөнгөн дүн **MNT (төгрөг)**-өөр илэрхийлэгдэнэ, валют хөрвүүлэлт хийгддэггүй.

## Хөгжүүлэлтийн талаар нэмэлт мэдээлэл

`AGENTS.md` файлд төслийн дизайны шийдвэрүүд, нарийн ширийн зүйлс (жишээ нь: "идэвхтэй зээл" гэдэг нь яг `status == 'active'` гэсэн үг, `overdue`-с ялгаатай; MCP хариуны JSON бүтцийн конвенц г.м) илүү дэлгэрэнгүй бичигдсэн.