from datetime import datetime, timezone

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
from app.services.r2 import (
    abort_multipart_upload,
    complete_multipart_upload,
    generate_presigned_part_url,
)
from logger import get_logger

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


@router.post("/{session_id}/chunks/presign", response_model=PresignResponse)
async def presign_chunk(
    session_id: str,
    body: PresignRequest,
    user: dict = Depends(get_current_user),
) -> PresignResponse:
    """
    Genera presigned URLs para subir una parte (chunk) del video y del IMU.
    El móvil hace PUT directo a R2 ��� los datos nunca pasan por el backend.
    """
    db = get_db()
    session = _get_session_or_raise(db, session_id, user["uid"])

    if session["status"] not in _RECORDABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"La sesión está en estado '{session['status']}', no se puede grabar.",
        )

    video_upload_id = session["videoUpload"]["uploadId"]
    imu_upload_id = session["imuUpload"]["uploadId"]

    video_url = generate_presigned_part_url(session["videoKey"], video_upload_id, body.partNumber)
    imu_url = generate_presigned_part_url(session["imuKey"], imu_upload_id, body.partNumber)
    logger.info(
        "Presign chunk: sessionId=%s uid=%s part=%s",
        session_id,
        user["uid"],
        body.partNumber,
    )

    return PresignResponse(
        uploadId=video_upload_id,
        videoPresignedUrl=video_url,
        imuPresignedUrl=imu_url,
        partNumber=body.partNumber,
    )


@router.post("/{session_id}/chunks/confirm", response_model=ConfirmChunkResponse)
async def confirm_chunk(
    session_id: str,
    body: ConfirmChunkRequest,
    user: dict = Depends(get_current_user),
) -> ConfirmChunkResponse:
    """
    Confirma que un chunk fue subido exitosamente a R2.
    Guarda el ETag de video e IMU en Firestore para el ensamblado final.
    """
    db = get_db()
    _get_session_or_raise(db, session_id, user["uid"])

    chunk_id = f"{session_id}_part{body.partNumber:03d}"
    db.collection("chunks").document(chunk_id).set(
        {
            "chunkId": chunk_id,
            "sessionId": session_id,
            "partNumber": body.partNumber,
            "videoETag": body.videoETag,
            "imuETag": body.imuETag,
            "uploadedAt": datetime.now(tz=timezone.utc),
            "status": "uploaded",
        }
    )
    logger.info("Chunk confirmed: sessionId=%s uid=%s part=%s", session_id, user["uid"], body.partNumber)

    return ConfirmChunkResponse(chunkId=chunk_id, status="confirmed")


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
    logger.info("Completing session: sessionId=%s uid=%s chunks=%s", session_id, user["uid"], len(chunks))

    video_parts = [{"PartNumber": c["partNumber"], "ETag": c["videoETag"]} for c in chunks]
    imu_parts = [{"PartNumber": c["partNumber"], "ETag": c["imuETag"]} for c in chunks]

    complete_multipart_upload(
        session["videoKey"],
        session["videoUpload"]["uploadId"],
        video_parts,
    )
    complete_multipart_upload(
        session["imuKey"],
        session["imuUpload"]["uploadId"],
        imu_parts,
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
    session = _get_session_or_raise(db, session_id, user["uid"])

    abort_multipart_upload(session["videoKey"], session["videoUpload"]["uploadId"])
    abort_multipart_upload(session["imuKey"], session["imuUpload"]["uploadId"])
    logger.info("Session aborted: sessionId=%s uid=%s", session_id, user["uid"])

    db.collection("sessions").document(session_id).update(
        {
            "status": "aborted",
            "endedAt": datetime.now(tz=timezone.utc),
        }
    )

    return {"status": "aborted"}
