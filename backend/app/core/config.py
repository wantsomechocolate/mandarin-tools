from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str

    # Auth
    secret_key: str
    algorithm: str = "HS256"
    # No prod/dev config split exists yet (single environment so far - see
    # CLAUDE.md's Deployment section) - still override-able via
    # MANDARIN_TOOLS_ACCESS_TOKEN_EXPIRE_MINUTES once one does.
    access_token_expire_minutes: int = 60

    # App
    app_name: str = "Mandarin Tools"
    debug: bool = False

    model_config = {"env_prefix": "MANDARIN_TOOLS_"}

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


settings = Settings()