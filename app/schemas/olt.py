from datetime import datetime

from pydantic import BaseModel, Field

from app.models.olt import OLTModel, OLTPlatform, OLTStatus


class OLTCreate(BaseModel):
    name: str = Field(..., max_length=128)
    host: str = Field(..., max_length=45)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    model: OLTModel
    software_version: str | None = None
    location: str | None = None
    description: str | None = Field(default=None, max_length=512)
    ssh_username: str = Field(..., max_length=64)
    ssh_password: str = Field(..., max_length=256)
    enable_password: str | None = Field(default=None, max_length=256)


class OLTUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    host: str | None = Field(default=None, max_length=45)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    software_version: str | None = None
    location: str | None = None
    description: str | None = Field(default=None, max_length=512)
    ssh_username: str | None = None
    ssh_password: str | None = None
    enable_password: str | None = None
    status: OLTStatus | None = None


class OLTResponse(BaseModel):
    id: int
    name: str
    host: str
    ssh_port: int
    model: OLTModel
    platform: OLTPlatform
    software_version: str | None
    location: str | None
    description: str | None
    status: OLTStatus
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class OLTHealthResponse(BaseModel):
    olt_id: int
    name: str
    host: str
    reachable: bool
    uptime: str | None = None
    software_version: str | None = None
    error: str | None = None
