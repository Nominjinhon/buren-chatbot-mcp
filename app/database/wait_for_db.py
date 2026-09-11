"""Blocks until the configured database is reachable.

Used by the Docker entrypoint before running migrations. This project has no
docker-compose-managed `db` service to `depends_on: condition: service_healthy`
against - it targets the host machine's own Postgres - so readiness is
polled here instead.
"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.settings import get_settings

MAX_ATTEMPTS = 60
DELAY_SECONDS = 1.0


async def wait_for_db() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                print("Database is reachable.")
                return
            except Exception as exc:
                print(f"Database not ready (attempt {attempt}/{MAX_ATTEMPTS}): {exc}")
                await asyncio.sleep(DELAY_SECONDS)
    finally:
        await engine.dispose()

    print(f"Database still unreachable after {MAX_ATTEMPTS} attempts.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(wait_for_db())
