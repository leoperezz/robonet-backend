from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.models.user import RegisterDeviceRequest, UserResponse
from app.services.firebase import get_db
from logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post("/register-device", response_model=UserResponse)
async def register_device(
    body: RegisterDeviceRequest,
    user: dict = Depends(get_current_user),
) -> UserResponse:
    """
    Registra o actualiza la información del dispositivo del usuario en Firestore.
    Usar merge=True para no sobreescribir campos previos (ej. historial de sesiones).
    """
    db = get_db()
    uid: str = user["uid"]
    now = datetime.now(tz=timezone.utc)
    logger.info("Register device: uid=%s", uid)

    device_info = body.deviceInfo.model_dump() if body.deviceInfo else {}

    db.collection("users").document(uid).set(
        {
            "uid": uid,
            "email": user.get("email", ""),
            "displayName": user.get("name", ""),
            "deviceInfo": device_info,
            "updatedAt": now,
            "createdAt": now,
        },
        merge=True,
    )

    return UserResponse(
        uid=uid,
        email=user.get("email", ""),
        displayName=user.get("name", ""),
        deviceInfo=device_info,
        updatedAt=now,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)) -> UserResponse:
    """Devuelve el perfil del usuario autenticado desde Firestore."""
    db = get_db()
    doc = db.collection("users").document(user["uid"]).get()
    if doc.exists:
        data = doc.to_dict()
        return UserResponse(**data)
    return UserResponse(uid=user["uid"], email=user.get("email", ""))
