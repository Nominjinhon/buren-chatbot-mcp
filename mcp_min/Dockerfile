FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir "mcp[cli]" "uvicorn[standard]"

COPY mcp_min/server.py .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
