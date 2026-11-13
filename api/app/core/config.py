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
        # The prefixed name is what the images and every .env.example use; accepting only the
        # bare one made a deployed container fall back to localhost without a word.
        validation_alias=AliasChoices("SITEWARRANT_DATABASE_URL", "DATABASE_URL", "database_url"),
    )
    store_artifacts: bool = Field(
        default=True,
        validation_alias=AliasChoices("SITEWARRANT_STORE_ARTIFACTS", "store_artifacts"),
        description="Write HTML, DOM and PNG artifacts for each capture.",
    )
    artifacts_dir: Path = Field(
        default=Path("artifacts"),
        validation_alias=AliasChoices("ARTIFACTS_DIR", "artifacts_dir"),
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
    llm_base_url: str = Field(
        default="https://opencode.ai/zen/go/v1",
        validation_alias=AliasChoices("SITEWARRANT_LLM_BASE_URL", "llm_base_url"),
    )
    llm_model: str = Field(
        default="deepseek-v4.1-flash",
        validation_alias=AliasChoices("SITEWARRANT_LLM_MODEL", "llm_model"),
    )
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SITEWARRANT_LLM_API_KEY", "OPENCODE_GO_API_KEY", "llm_api_key"
        ),
    )
    llm_cassette: str = Field(
        default="",
        validation_alias=AliasChoices("SITEWARRANT_LLM_CASSETTE", "llm_cassette"),
    )
    llm_timeout_s: float = Field(
        default=120.0,
        validation_alias=AliasChoices("SITEWARRANT_LLM_TIMEOUT_S", "llm_timeout_s"),
    )
    # Ceiling for the estimated model cost of one audit. None switches the ceiling off; the
    # estimate itself always comes from the versioned price file.
    audit_cost_limit_usd: float | None = Field(
        default=0.25,
        validation_alias=AliasChoices("SITEWARRANT_AUDIT_COST_LIMIT_USD", "audit_cost_limit_usd"),
    )
    # The Chief Auditor's prose about a cluster the deterministic layer built. One extra model
    # call per audit that produced a root cause; a failure leaves the measured text in place.
    chief_narration: bool = Field(
        default=True,
        validation_alias=AliasChoices("SITEWARRANT_CHIEF_NARRATION", "chief_narration"),
    )

    @property
    def viewport_list(self) -> tuple[str, ...]:
        """The measured viewports, fixed rather than adaptive.

        Comparing audits between agent versions needs identical conditions, so the set is
        configuration with a default, not a per-site decision.
        """
        parsed = tuple(item.strip() for item in self.viewports.split(",") if item.strip())
        return parsed or ("1440x900",)

    @property
    def llm_cassette_path(self) -> Path:
        """Where a recorded conversation lives; tests replay it instead of calling a model."""
        return Path(self.llm_cassette)

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
