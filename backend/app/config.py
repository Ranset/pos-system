from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Base de Datos ──────────────────────────────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "pos_user"
    DB_PASSWORD: str = "pos_password"
    DB_NAME: str = "pos_db"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ── JWT ────────────────────────────────────────────────────────────────────
    SECRET_KEY: str = "cambia-esta-clave-en-produccion-minimo-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 horas = turno completo

    # ── Servidor ───────────────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DEBUG: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()
