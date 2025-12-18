from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = Field("mcp-0", alias="MCP0_APP_NAME")
    host: str = Field("0.0.0.0", alias="MCP0_HOST")
    port: int = Field(8010, alias="MCP0_PORT")
    provider_list: Optional[str] = Field(None, alias="MCP0_PROVIDERS")
    http_routes: Optional[str] = Field(None, alias="MCP0_HTTP_ROUTES")
    request_timeout: float = Field(10.0, alias="MCP0_TIMEOUT_SECONDS")
    allow_origins: str | None = Field(None, alias="MCP0_ALLOW_ORIGINS")
    admin_token: Optional[str] = Field(None, alias="MCP0_ADMIN_TOKEN")
    # Accept any of the common env names for GitHub tokens
    github_token: Optional[str] = Field(None, alias="GITHUB_MCP_TOKEN")
    github_token_alt: Optional[str] = Field(None, alias="GITHUB_PERSONAL_ACCESS_TOKEN")
    github_token_std: Optional[str] = Field(None, alias="GITHUB_TOKEN")
    github_personal_token: Optional[str] = Field(None, alias="GITHUB_PERSONAL_ACCESS_TOKEN")
    enable_dynamic_github_tools: bool = Field(False, alias="MCP0_ENABLE_DYNAMIC_GITHUB_TOOLS")
    github_tool_source: Optional[str] = Field(None, alias="GITHUB_MCP_TOOLS")

    # GitHub Models (OpenAI-compatible) configuration
    github_models_api_base: str = Field(
        "https://models.inference.ai.azure.com", alias="GITHUB_MODELS_API_BASE"
    )
    github_model: str = Field("gpt-4o-mini", alias="GITHUB_MODEL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def cors_origins(self) -> List[str]:
        if not self.allow_origins:
            return ["*"]
        return [origin.strip() for origin in self.allow_origins.split(",") if origin.strip()]

    @property
    def effective_github_token(self) -> Optional[str]:
        return self.github_token or self.github_token_std or self.github_token_alt or self.github_personal_token


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
