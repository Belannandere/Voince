from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    upload_dir: str = "uploads"
    max_upload_mb: int = 10
    database_url: str = ""

    # ---------- Ollama / AI ----------
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:1b"
    ollama_num_ctx: int = 2048
    ollama_num_predict: int = 600
    ollama_keep_alive: str = "15m"
    ollama_timeout: float = 90.0
    ollama_num_thread: int = 2
    ollama_max_input_chars: int = 8000

    secret_key: str = "change-me-in-production"
    session_max_age: int = 60 * 60 * 24 * 14

    port: int = 8000
    https_only: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    oauth_redirect_base_url: str = "http://localhost:8000"

    # ---------- Billing (Trybit) ----------
    trybit_api_url: str = "https://api.trybit.com"
    trybit_api_key: str = ""
    trybit_shop_id: str = ""
    # Symmetric secret used to verify JWT-HS256 postbacks.
    # Get this from the Trybit dashboard ("Secret Key").
    trybit_webhook_secret: str = ""
    # Optional: PEM public key for RSA-based verification (if Trybit
    # ever confirms RSA instead of JWT). Leave empty unless needed.
    trybit_webhook_public_key: str = ""

    # Server-side source of truth for prices (USD).
    pro_price: str = "10"
    min_topup: str = "10"
    max_topup: str = "500"

    public_base_url: str = "http://localhost:8000"

    def model_post_init(self, __context) -> None:
        if not self.database_url:
            self.database_url = (
                f"sqlite:///{(BASE_DIR / 'invoices.db').as_posix()}"
            )

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()