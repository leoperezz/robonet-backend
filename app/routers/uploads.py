from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_user
from app.models.session import (
    ConfirmChunkRequest,
    ConfirmChunkResponse,
    CompleteSessionResponse,
    PresignRequest,
    PresignResponse,
)
from app.services.firebase import get_db
from app.services.r2 import generate_presigned_put_url
from app.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

_RECORDABLE_STATUSES = {"recording", "uploading"}


def _get_session_or_raise(db, session_id: str, uid: str) -> dict:
    """Obtiene la sesión de Firestore y valida que pertenezca al usuario."""
    doc = db.collection("sessions").document(session_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    data = doc.to_dict()
    if data["userId"] != uid:
        raise HTTPException(status_code=403, detail="Sin permisos para esta sesión")
    return data


def _chunk_object_key(session: dict, stream: str, part_number: int) -> str:
    """Construye la key R2 para el chunk (objeto por chunk)."""
    if stream == "video":
        prefix = session.get("videoPrefix")
        suffix = f"part{part_number:03d}.mp4"
    else:
        prefix = session.get("imuPrefix")
        suffix = f"part{part_number:03d}.ndjson"

    if not prefix:
        # Fallback defensivo si la sesión no tiene prefijos (legacy).
        base_prefix = f"sessions/{session.get('userId')}/{session.get('sessionId')}"
        prefix = f"{base_prefix}/{stream}"

    return f"{prefix}/{suffix}"


@router.post("/{session_id}/chunks/presign", response_model=PresignResponse)
async def presign_chunk(
    session_id: str,
    body: PresignRequest,
    user: dict = Depends(get_current_user),
) -> PresignResponse:
    """
    Genera presigned URL para subir una parte (chunk) de `video` o `imu`.
    El cliente hace PUT directo a R2; los datos nunca pasan por el backend.
    """
    db = get_db()
    session = _get_session_or_raise(db, session_id, user["uid"])

    if session["status"] not in _RECORDABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"La sesión está en estado '{session['status']}', no se puede grabar.",
        )

    key = _chunk_object_key(session, body.stream, body.partNumber)
    content_type = "video/mp4" if body.stream == "video" else "application/x-ndjson"
    presigned_url = generate_presigned_put_url(key, content_type=content_type)
    logger.info(
        "Presign chunk: sessionId=%s uid=%s stream=%s part=%s",
        session_id,
        user["uid"],
        body.stream,
        body.partNumber,
    )

    return PresignResponse(
        presignedUrl=presigned_url,
        partNumber=body.partNumber,
        stream=body.stream,
        objectKey=key,
    )


@router.post("/{session_id}/chunks/confirm", response_model=ConfirmChunkResponse)
async def confirm_chunk(
    session_id: str,
    body: ConfirmChunkRequest,
    user: dict = Depends(get_current_user),
) -> ConfirmChunkResponse:
    """
    Confirma que un chunk fue subido exitosamente a R2 (para `video` o `imu`).

    El backend persiste el receipt en Firestore en `chunks/{chunkId}` y
    cuando ambos receipts existen marca `status="readyForProcess"`.
    """
    db = get_db()
    session = _get_session_or_raise(db, session_id, user["uid"])

    chunk_id = f"{session_id}_part{body.partNumber:03d}"
    chunk_ref = db.collection("chunks").document(chunk_id)
    existing_doc = chunk_ref.get()
    existing = existing_doc.to_dict() if existing_doc.exists else {}

    now = datetime.now(tz=timezone.utc)
    payload: dict = {
        "chunkId": chunk_id,
        "sessionId": session_id,
        "partNumber": body.partNumber,
    }

    if body.stream == "video":
        payload["videoKey"] = _chunk_object_key(session, "video", body.partNumber)
        payload.update(
            {
                "videoETag": body.etag,
                "videoStartTsUs": body.startTsUs,
                "videoEndTsUs": body.endTsUs,
                "videoUploadedAt": now,
            }
        )
    else:
        payload["imuKey"] = _chunk_object_key(session, "imu", body.partNumber)
        payload.update(
            {
                "imuETag": body.etag,
                "imuStartTsUs": body.startTsUs,
                "imuEndTsUs": body.endTsUs,
                "sensorIds": body.sensorIds or [],
                "imuUploadedAt": now,
            }
        )

    # Determine ready status after this update.
    video_ready = ("videoETag" in existing and existing.get("videoETag")) or (
        body.stream == "video" and body.etag
    )
    imu_ready = ("imuETag" in existing and existing.get("imuETag")) or (
        body.stream == "imu" and body.etag
    )
    if video_ready and imu_ready:
        status = "readyForProcess"
    elif body.stream == "video":
        status = "videoUploaded"
    else:
        status = "imuUploaded"

    payload["status"] = status
    chunk_ref.set(payload, merge=True)

    if status == "readyForProcess":
        # Prototipo de cola para el worker Python/ingest-worker.
        # Cuando exista Redis se reemplaza por XADD.
        db.collection("processingQueue").document(chunk_id).set(
            {
                "chunkId": chunk_id,
                "sessionId": session_id,
                "partNumber": body.partNumber,
                "createdAt": now,
                "status": "queued",
            },
            merge=True,
        )

    logger.info(
        "Chunk confirmed: sessionId=%s uid=%s stream=%s part=%s status=%s",
        session_id,
        user["uid"],
        body.stream,
        body.partNumber,
        status,
    )

    return ConfirmChunkResponse(chunkId=chunk_id, status=status)


@router.get("/{session_id}/chunks", response_model=list[dict[str, Any]])
async def list_chunks(session_id: str, user: dict = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Devuelve los receipts confirmados por `partNumber` para una sesión."""
    db = get_db()
    _get_session_or_raise(db, session_id, user["uid"])

    chunks_docs = (
        db.collection("chunks")
        .where("sessionId", "==", session_id)
        .order_by("partNumber")
        .stream()
    )
    return [doc.to_dict() for doc in chunks_docs]


@router.post("/{session_id}/complete", response_model=CompleteSessionResponse)
async def complete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> CompleteSessionResponse:
    """
    Finaliza la sesión: completa los multipart uploads en R2 ensamblando
    todas las partes confirmadas, y actualiza el estado en Firestore.
    """
    db = get_db()
    session = _get_session_or_raise(db, session_id, user["uid"])

    chunks_docs = (
        db.collection("chunks")
        .where("sessionId", "==", session_id)
        .order_by("partNumber")
        .stream()
    )
    chunks = [doc.to_dict() for doc in chunks_docs]

    if not chunks:
        raise HTTPException(status_code=400, detail="No hay chunks confirmados para esta sesión")
    logger.info(
        "Completing session: sessionId=%s uid=%s chunks=%s",
        session_id,
        user["uid"],
        len(chunks),
    )

    missing_video = [c["partNumber"] for c in chunks if not c.get("videoETag")]
    missing_imu = [c["partNumber"] for c in chunks if not c.get("imuETag")]
    if missing_video or missing_imu:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan receipts antes de completar. video_missing={missing_video} imu_missing={missing_imu}",
        )

    db.collection("sessions").document(session_id).update(
        {
            "status": "complete",
            "endedAt": datetime.now(tz=timezone.utc),
            "totalChunks": len(chunks),
        }
    )
    logger.info("Session completed: sessionId=%s uid=%s", session_id, user["uid"])

    return CompleteSessionResponse(
        sessionId=session_id,
        status="complete",
        chunks=len(chunks),
    )


@router.delete("/{session_id}/abort", status_code=200)
async def abort_session(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Aborta la sesión: cancela los multipart uploads en R2 y marca la sesión como abortada.
    Siempre llamar esto cuando el usuario cancela una grabación para liberar storage.
    """
    db = get_db()
    _get_session_or_raise(db, session_id, user["uid"])
    logger.info("Session aborted: sessionId=%s uid=%s", session_id, user["uid"])

    db.collection("sessions").document(session_id).update(
        {
            "status": "aborted",
            "endedAt": datetime.now(tz=timezone.utc),
        }
    )

    return {"status": "aborted"}
