from datetime import datetime
from typing import Any

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


class PresignResponse(BaseModel):
    uploadId: str
    videoPresignedUrl: str
    imuPresignedUrl: str
    partNumber: int


class ConfirmChunkRequest(BaseModel):
    partNumber: int = Field(..., ge=1)
    videoETag: str
    imuETag: str


class ConfirmChunkResponse(BaseModel):
    chunkId: str
    status: str


class CompleteSessionResponse(BaseModel):
    sessionId: str
    status: str
    chunks: int
