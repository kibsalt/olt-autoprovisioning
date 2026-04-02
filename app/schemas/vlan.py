from datetime import datetime

from pydantic import BaseModel, Field

from app.models.vlan import VLANServiceType


class VLANCreate(BaseModel):
    vlan_tag: int = Field(..., ge=1, le=4094)
    name: str = Field(..., max_length=128)
    service_type: VLANServiceType
    description: str | None = None


class VLANUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    service_type: VLANServiceType | None = None
    description: str | None = None


class VLANResponse(BaseModel):
    id: int
    vlan_tag: int
    name: str
    service_type: VLANServiceType
    description: str | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
