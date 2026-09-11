FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (separate layer, cached across code-only changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
