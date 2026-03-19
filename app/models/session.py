from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MultipartUploadInfo(BaseModel):
    uploadId: str
    completedParts: list[dict[str, Any]] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    deviceInfo: dict[str, Any] | None = None


class SessionResponse(BaseModel):
    sessionId: str
    userId: str
    status: str
    startedAt: datetime
    endedAt: datetime | None = None
    videoKey: str
    imuKey: str
    videoUpload: MultipartUploadInfo | None = None
    imuUpload: MultipartUploadInfo | None = None
    deviceInfo: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    totalChunks: int | None = None


class PresignRequest(BaseModel):
    partNumber: int = Field(..., ge=1, description="Número de parte (1-based)")
    stream: Literal["video", "imu"] = Field(..., description="Stream a presign (video o imu)")


class PresignResponse(BaseModel):
    uploadId: str
    partNumber: int
    stream: Literal["video", "imu"]
    presignedUrl: str


class ConfirmChunkRequest(BaseModel):
    partNumber: int = Field(..., ge=1)
    stream: Literal["video", "imu"]
    etag: str
    startTsUs: int | None = Field(
        default=None,
        description="Timestamp inicio (base de tiempo del origen) en microsegundos.",
    )
    endTsUs: int | None = Field(
        default=None,
        description="Timestamp fin (base de tiempo del origen) en microsegundos.",
    )
    sensorIds: list[int] | None = Field(
        default=None,
        description="IDs de sensores presentes (solo para IMU).",
    )


class ConfirmChunkResponse(BaseModel):
    chunkId: str
    status: str


class CompleteSessionResponse(BaseModel):
    sessionId: str
    status: str
    chunks: int


class SyncMetaRequest(BaseModel):
    """
    Metadatos ligeros del video para que la capa 'Synchronizer' (Raspberry)
    sepa qué ventana temporal del stream IMU debe segmentar para este chunk.
    """

    partNumber: int = Field(..., ge=1)
    videoStartTsUs: int
    videoEndTsUs: int
    ptsStart: int | None = None
    ptsEnd: int | None = None
    nonce: str | None = None
