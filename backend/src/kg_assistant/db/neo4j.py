import asyncio
import logging

from neo4j import AsyncDriver, AsyncGraphDatabase, Query

from kg_assistant.core.config import Settings

logger = logging.getLogger(__name__)


class Neo4jConnectionManager:
    """One driver per application lifespan; sessions are scoped to individual operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._driver: AsyncDriver | None = None

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4j connection manager has not been started")
        return self._driver

    async def start(self) -> None:
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(
                    self.settings.neo4j_username,
                    self.settings.neo4j_password.get_secret_value(),
                ),
                connection_timeout=self.settings.neo4j_connection_timeout,
                connection_acquisition_timeout=self.settings.neo4j_health_timeout,
                max_transaction_retry_time=0,
            )

    async def close(self) -> None:
        if self._driver is not None:
            try:
                await self._driver.close()
            finally:
                self._driver = None

    async def healthy(self) -> bool:
        try:
            async with asyncio.timeout(self.settings.neo4j_health_timeout):
                async with self.driver.session(database=self.settings.neo4j_database) as session:
                    result = await session.run(
                        Query("RETURN 1 AS ok", timeout=self.settings.neo4j_health_timeout)
                    )
                    record = await result.single(strict=True)
                    return record is not None and record["ok"] == 1
        except Exception as exc:
            # Log only the class: driver error messages can contain infrastructure details.
            logger.warning("neo4j_health_failed:%s", type(exc).__name__)
            return False
