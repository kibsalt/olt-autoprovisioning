from datetime import datetime

from pydantic import BaseModel, Field

from app.models.service_profile import ServiceType


class ServiceProfileCreate(BaseModel):
    name: str = Field(..., max_length=128)
    service_type: ServiceType
    upstream_profile_id: int | None = None
    downstream_profile_id: int | None = None
    vlan_id: int | None = None
    gem_port: int | None = None
    tcont_id: int | None = None
    description: str | None = None


class ServiceProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    service_type: ServiceType | None = None
    upstream_profile_id: int | None = None
    downstream_profile_id: int | None = None
    vlan_id: int | None = None
    gem_port: int | None = None
    tcont_id: int | None = None
    description: str | None = None


class ServiceProfileResponse(BaseModel):
    id: int
    name: str
    service_type: ServiceType
    upstream_profile_id: int | None
    downstream_profile_id: int | None
    vlan_id: int | None
    gem_port: int | None
    tcont_id: int | None
    description: str | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class ApplyServiceRequest(BaseModel):
    service_profile_id: int
    vlan_id: int | None = None
