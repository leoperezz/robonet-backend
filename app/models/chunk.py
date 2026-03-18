from datetime import datetime

from pydantic import BaseModel, Field


class ChunkDocument(BaseModel):
    """Representa un documento en la colección 'chunks' de Firestore."""

    chunkId: str
    sessionId: str
    partNumber: int = Field(..., ge=1)
    videoETag: str
    imuETag: str
    uploadedAt: datetime
    status: str = "uploaded"
