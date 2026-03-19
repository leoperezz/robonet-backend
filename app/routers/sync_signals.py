from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_user
from app.models.session import SyncMetaRequest
from app.services.firebase import get_db
from app.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


def _get_session_or_raise(db, session_id: str, uid: str) -> dict:
    doc = db.collection("sessions").document(session_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    data = doc.to_dict()
    if data["userId"] != uid:
        raise HTTPException(status_code=403, detail="Sin permisos para esta sesión")
    return data


@router.post("/{session_id}/syncmeta", status_code=201)
async def add_sync_meta(
    session_id: str,
    body: SyncMetaRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Recibe VideoSyncMeta desde la app móvil para un `partNumber`/`chunkIndex`.
    La Raspberry (más adelante) consultará estos metadatos para segmentar el stream IMU.
    """
    db = get_db()
    _get_session_or_raise(db, session_id, user["uid"])

    now = datetime.now(tz=timezone.utc)
    part = body.partNumber
    sync_id = f"{session_id}_part{part:03d}"

    db.collection("syncMeta").document(sync_id).set(
        {
            "syncId": sync_id,
            "sessionId": session_id,
            "partNumber": part,
            "videoStartTsUs": body.videoStartTsUs,
            "videoEndTsUs": body.videoEndTsUs,
            "ptsStart": body.ptsStart,
            "ptsEnd": body.ptsEnd,
            "nonce": body.nonce,
            "createdAt": now,
            "consumedAt": None,
        },
        merge=True,
    )

    logger.info("SyncMeta stored: sessionId=%s part=%s", session_id, part)
    return {"syncId": sync_id, "status": "stored"}


@router.get("/{session_id}/syncmeta/pending", status_code=200)
async def list_pending_sync_meta(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> list[dict]:
    """
    Endpoint de polling para la Raspberry (prototipo).
    Devuelve syncMeta no consumidos.

    Nota: por ser POC, se filtra en memoria en lugar de depender de queries
    complejas sobre Firestore (nulls).
    """
    db = get_db()
    _get_session_or_raise(db, session_id, user["uid"])

    docs = (
        db.collection("syncMeta")
        .where("sessionId", "==", session_id)
        .order_by("partNumber")
        .stream()
    )
    pending: list[dict] = []
    for doc in docs:
        data = doc.to_dict()
        if not data:
            continue
        consumed_at = data.get("consumedAt")
        if consumed_at is None:
            pending.append(data)
        if len(pending) >= 50:
            break

    return pending


@router.post("/{session_id}/syncmeta/{part_number}/consume", status_code=200)
async def consume_sync_meta(
    session_id: str,
    part_number: int,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    La Raspberry marca un `syncMeta` como consumido (prototipo).
    """
    db = get_db()
    _get_session_or_raise(db, session_id, user["uid"])

    sync_id = f"{session_id}_part{part_number:03d}"
    now = datetime.now(tz=timezone.utc)
    db.collection("syncMeta").document(sync_id).set(
        {"consumedAt": now, "consumedBy": user.get("uid", "")},
        merge=True,
    )
    logger.info("SyncMeta consumed: sessionId=%s part=%s", session_id, part_number)
    return {"syncId": sync_id, "status": "consumed"}

