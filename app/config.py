"""
Configuração central da aplicação.
Toda configuração vem de variáveis de ambiente (12-factor) — nenhum segredo hardcoded.
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg2://hamburgueria:dev_local_only_pw@localhost:5432/hamburgueria_fase1"
    jwt_secret_key: str = "dev-only-secret-change-in-production-via-env-var"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24  # 24h — validade de sessão para esta fase

    idempotency_ttl_hours: int = 48  # §1.24 do contrato técnico

    @field_validator("database_url")
    @classmethod
    def normaliza_esquema_postgres(cls, v: str) -> str:
        """Provedores de hospedagem (Render, Heroku, etc.) costumam entregar
        a URL do banco como 'postgres://' ou 'postgresql://' — o driver que
        este projeto usa (psycopg2) exige explicitamente 'postgresql+psycopg2://'.
        Normaliza aqui, uma vez só, para nunca depender de o hospedeiro usar
        exatamente o formato que o código espera."""
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg2://", 1)
        if v.startswith("postgresql://") and "+psycopg2" not in v:
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v


settings = Settings()

