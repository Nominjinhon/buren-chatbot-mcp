FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "mcp[cli]" \
    "uvicorn[standard]" \
    "sqlalchemy[asyncio]>=2.0.30" \
    "psycopg[binary]>=3.1" \
    "pydantic>=2.7" \
    "pydantic-settings>=2.3" \
    "python-dotenv>=1.0"

COPY app/__init__.py app/__init__.py
COPY app/config app/config
COPY app/database app/database
COPY app/schemas app/schemas
COPY app/services app/services
COPY app/mcp_servers app/mcp_servers
COPY mcp_service/server.py .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
