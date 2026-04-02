from datetime import datetime

from pydantic import BaseModel, Field

from app.models.bandwidth_profile import DBAType, Direction


class BandwidthProfileCreate(BaseModel):
    name: str = Field(..., max_length=128)
    traffic_table_index: int | None = None
    cir: int = Field(..., ge=0, description="Committed information rate in kbps")
    pir: int = Field(..., ge=0, description="Peak information rate in kbps")
    cbs: int = Field(default=0, ge=0)
    pbs: int = Field(default=0, ge=0)
    dba_type: DBAType = DBAType.TYPE3
    direction: Direction
    description: str | None = None


class BandwidthProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    traffic_table_index: int | None = None
    cir: int | None = Field(default=None, ge=0)
    pir: int | None = Field(default=None, ge=0)
    cbs: int | None = Field(default=None, ge=0)
    pbs: int | None = Field(default=None, ge=0)
    dba_type: DBAType | None = None
    direction: Direction | None = None
    description: str | None = None


class BandwidthProfileResponse(BaseModel):
    id: int
    name: str
    traffic_table_index: int | None
    cir: int
    pir: int
    cbs: int
    pbs: int
    dba_type: DBAType
    direction: Direction
    description: str | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
