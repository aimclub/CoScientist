"""Lightweight façade settings that do not import the full RAG configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CodesynapseIntegrationSettings(BaseSettings):
    enabled: bool = False
    mongo_uri: str | None = None
    mongo_database: str = "coscientist"
    a2a_public_url: str | None = None

    model_config = SettingsConfigDict(env_prefix="CODESYNAPSE_", extra="ignore")

    def missing_readiness_requirements(self) -> list[str]:
        if not self.enabled:
            return []
        return [name for name in ("mongo_uri", "a2a_public_url") if not getattr(self, name)]
