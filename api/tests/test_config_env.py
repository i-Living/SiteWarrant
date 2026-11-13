import pytest

from app.core.config import Settings


def test_the_prefixed_database_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """A container sets SITEWARRANT_DATABASE_URL; accepting only DATABASE_URL meant localhost."""
    monkeypatch.setenv("SITEWARRANT_DATABASE_URL", "postgresql+asyncpg://other@db:5432/sitewarrant")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings()
    assert settings.database_url.endswith("@db:5432/sitewarrant")


def test_the_bare_name_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SITEWARRANT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bare@db:5432/sitewarrant")
    assert Settings().database_url.endswith("@db:5432/sitewarrant")


def test_the_default_is_loopback_not_a_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing in the shipped defaults should point at a host other than this machine."""
    monkeypatch.delenv("SITEWARRANT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "app.core.config.Settings.model_config",
        {**Settings.model_config, "env_file": None},
        raising=False,
    )
    assert "localhost" in Settings(_env_file=None).database_url
