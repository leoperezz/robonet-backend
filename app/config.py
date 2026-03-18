import base64
import json
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Firebase ──────────────────────────────────────────────────────────────
    # Opción A: ruta a un archivo local (desarrollo)
    firebase_credentials_path: str = "firebase-credentials.json"
    # Opción B: contenido del JSON en base64 (producción / CI)
    firebase_credentials_b64: str = ""

    # ── Cloudflare R2 ─────────────────────────────────────────────────────────
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "sessions-poc"
    # Se construye automáticamente si no se provee
    r2_endpoint: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    chunk_duration_seconds: int = 30

    def model_post_init(self, __context: object) -> None:  # noqa: ANN001
        if not self.r2_endpoint and self.r2_account_id:
            object.__setattr__(
                self,
                "r2_endpoint",
                f"https://{self.r2_account_id}.r2.cloudflarestorage.com",
            )

    def resolved_firebase_credentials_path(self) -> str:
        """
        Devuelve la ruta al archivo de credenciales de Firebase.
        Si se configuró FIREBASE_CREDENTIALS_B64, decodifica y escribe
        un archivo temporal para que firebase-admin pueda leerlo.
        """
        if self.firebase_credentials_b64:
            decoded = base64.b64decode(self.firebase_credentials_b64)
            creds = json.loads(decoded)
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="firebase_creds_"
            )
            json.dump(creds, tmp)
            tmp.flush()
            return tmp.name

        path = Path(self.firebase_credentials_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Firebase credentials file not found: {path}. "
                "Set FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS_B64."
            )
        return str(path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
