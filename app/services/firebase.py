"""
Firebase manager — inicialización, Firestore client y verificación de tokens.

Se inicializa UNA sola vez en el startup de la app (app/main.py).
Usa get_db() en cualquier router/service para obtener el cliente de Firestore.
"""

from __future__ import annotations

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials, firestore

from app.config import get_settings
from app.logger import get_logger

logger = get_logger(__name__)

_db: firestore.Client | None = None


def init_firebase() -> None:
    """
    Inicializa el SDK de Firebase Admin.
    Idempotente: no falla si ya fue inicializado (útil en tests).
    """
    global _db
    settings = get_settings()

    if not firebase_admin._apps:
        creds_path = settings.resolved_firebase_credentials_path()
        cred = credentials.Certificate(creds_path)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK inicializado correctamente.")
    else:
        logger.debug("Firebase Admin SDK ya estaba inicializado.")

    _db = firestore.client()
    logger.info("Firestore client listo")


def get_db() -> firestore.Client:
    """Devuelve el cliente de Firestore. Lanza RuntimeError si no se inicializó."""
    if _db is None:
        raise RuntimeError(
            "Firestore no inicializado. Asegurate de llamar init_firebase() en startup."
        )
    return _db


def verify_token(id_token: str) -> dict:
    """
    Verifica un Firebase ID Token y devuelve el decoded payload.
    Lanza ValueError con un mensaje legible si el token es inválido o expiró.
    """
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        return decoded
    except firebase_auth.ExpiredIdTokenError as exc:
        raise ValueError("El token de Firebase expiró. Renovalo y volvé a intentar.") from exc
    except firebase_auth.InvalidIdTokenError as exc:
        raise ValueError(f"Token de Firebase inválido: {exc}") from exc
    except Exception as exc:
        logger.exception("Error inesperado verificando token de Firebase")
        raise ValueError(f"Error verificando token: {exc}") from exc
