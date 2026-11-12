from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def viewport_size(value: str) -> tuple[int, int]:
    """Parse "WIDTHxHEIGHT" into CSS pixels."""
    width, _, height = value.partition("x")
    return int(width), int(height)


class Settings(BaseSettings):
    """Runtime configuration. Every value has a working local default.

    The default database URL carries the same throwaway credentials as
    infra/docker-compose.yml. They are development defaults, not secrets: a real
    deployment supplies DATABASE_URL from the environment.
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://sitewarrant:sitewarrant@localhost:5432/sitewarrant",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    artifacts_dir: Path = Field(
        default=Path("artifacts"),
        validation_alias=AliasChoices("ARTIFACTS_DIR", "artifacts_dir"),
    )
    viewport: str = Field(
        default="1440x900",
        validation_alias=AliasChoices("SITEWARRANT_VIEWPORT", "viewport"),
    )
    viewports: str = Field(
        default="390x844,768x1024,1440x900",
        validation_alias=AliasChoices("SITEWARRANT_VIEWPORTS", "viewports"),
    )
    page_timeout_ms: int = Field(
        default=30_000,
        validation_alias=AliasChoices("SITEWARRANT_PAGE_TIMEOUT_MS", "page_timeout_ms"),
    )
    allow_private_hosts: str = Field(
        default="",
        validation_alias=AliasChoices("SITEWARRANT_ALLOW_PRIVATE_HOSTS", "allow_private_hosts"),
    )
    db_null_pool: bool = Field(
        default=False,
        validation_alias=AliasChoices("SITEWARRANT_DB_NULL_POOL", "db_null_pool"),
    )
    capture_timeout_ms: int = Field(
        default=60_000,
        validation_alias=AliasChoices("SITEWARRANT_CAPTURE_TIMEOUT_MS", "capture_timeout_ms"),
    )
    user_agent: str = "SiteWarrant/0.1 (+https://github.com/i-Living/SiteWarrant)"

    @property
    def viewport_size(self) -> tuple[int, int]:
        return viewport_size(self.viewport)

    @property
    def viewport_list(self) -> tuple[str, ...]:
        """The measured viewports, fixed rather than adaptive.

        Comparing audits between agent versions needs identical conditions, so the set is
        configuration with a default, not a per-site decision.
        """
        parsed = tuple(item.strip() for item in self.viewports.split(",") if item.strip())
        return parsed or (self.viewport,)

    @property
    def allowed_private_host_set(self) -> frozenset[str]:
        """Hosts whose private addresses may be requested.

        A deployment-level allowlist, not a boolean: reaching the local fixture must not
        also permit a redirect to a cloud metadata address.
        """
        return frozenset(
            host.strip().lower() for host in self.allow_private_hosts.split(",") if host.strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
