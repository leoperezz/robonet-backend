from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr


class DeviceInfo(BaseModel):
    platform: str = ""
    model: str = ""
    osVersion: str = ""
    appVersion: str = ""


class RegisterDeviceRequest(BaseModel):
    deviceInfo: DeviceInfo | None = None


class UserResponse(BaseModel):
    uid: str
    email: str = ""
    displayName: str = ""
    deviceInfo: dict[str, Any] | None = None
    createdAt: datetime | None = None
    updatedAt: datetime | None = None
