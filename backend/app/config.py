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

    # ── Zona horaria local de la tienda ────────────────────────────────────────
    # `created_at`/`opened_at` se guardan en UTC (datetime.utcnow()). Los reportes
    # necesitan agrupar/mostrar en hora local. Como el backend suele correr en un
    # contenedor Docker en UTC, no podemos confiar en la hora del sistema:
    # se define explícitamente el desfase (horas) entre la hora local y UTC.
    # Ejemplo: Cuba (UTC-5) -> -5
    TIMEZONE_OFFSET_HOURS: float = -5

    # ── Terminal de pago Clip PinPad ────────────────────────────────────────────
    # Nunca se exponen vía AppConfig/`/config/map` (leído por cualquier cajero) —
    # solo aquí, igual que SECRET_KEY/DB_PASSWORD.
    CLIP_API_KEY: str = ""
    CLIP_API_SECRET: str = ""
    CLIP_API_BASE_URL: str = "https://api.payclip.io/f2f/pinpad/v1"

    model_config = {"env_file": ".env"}


settings = Settings()
