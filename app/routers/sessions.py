import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_user
from app.models.session import CreateSessionRequest, SessionResponse
from app.services.firebase import get_db
from app.services.r2 import create_multipart_upload
from app.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user: dict = Depends(get_current_user),
) -> SessionResponse:
    """
    Crea una sesión nueva y abre dos multipart uploads en R2:
    uno para video (.mp4) y otro para datos IMU (.ndjson).
    """
    db = get_db()
    uid: str = user["uid"]
    session_id = str(uuid.uuid4())

    video_key = f"sessions/{session_id}/video/final.mp4"
    imu_key = f"sessions/{session_id}/imu/final.ndjson"

    video_upload_id = create_multipart_upload(video_key, "video/mp4")
    imu_upload_id = create_multipart_upload(imu_key, "application/x-ndjson")
    logger.info("Session created: sessionId=%s uid=%s", session_id, uid)

    now = datetime.now(tz=timezone.utc)
    session_data = {
        "sessionId": session_id,
        "userId": uid,
        "status": "recording",
        "startedAt": now,
        "endedAt": None,
        "videoKey": video_key,
        "imuKey": imu_key,
        "videoUpload": {"uploadId": video_upload_id, "completedParts": []},
        "imuUpload": {"uploadId": imu_upload_id, "completedParts": []},
        "deviceInfo": body.deviceInfo or {},
        "summary": {},
    }

    db.collection("sessions").document(session_id).set(session_data)

    return SessionResponse(**session_data)


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    user: dict = Depends(get_current_user),
) -> list[SessionResponse]:
    """Lista las últimas 50 sesiones del usuario autenticado, más recientes primero."""
    db = get_db()
    docs = (
        db.collection("sessions")
        .where("userId", "==", user["uid"])
        .order_by("startedAt", direction="DESCENDING")
        .limit(50)
        .stream()
    )
    return [SessionResponse(**doc.to_dict()) for doc in docs]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> SessionResponse:
    """Devuelve el detalle de una sesión. Solo el dueño puede acceder."""
    db = get_db()
    doc = db.collection("sessions").document(session_id).get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    data = doc.to_dict()
    if data["userId"] != user["uid"]:
        raise HTTPException(status_code=403, detail="Sin permisos para ver esta sesión")

    return SessionResponse(**data)
