from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Config
    SECRET_KEY: str = "dev-secret-key"
    ENVIRONMENT: str = "development"

    # Database (optional - legacy modules use psycopg directly via kelava_db)
    DATABASE_URL: str = ""

    # Supabase (optional - standalone JWT auth used instead)
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
