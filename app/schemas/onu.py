from datetime import datetime

from pydantic import BaseModel, Field

from app.models.onu import AdminState, OperState


class ONUCreate(BaseModel):
    serial_number: str = Field(..., max_length=16)
    customer_id: str = Field(..., max_length=64)
    customer_name: str = Field(..., max_length=128, description="Used for WiFi SSID generation")
    frame: int = Field(..., ge=0)
    slot: int = Field(..., ge=0)
    port: int = Field(..., ge=0)
    onu_type: str = Field(..., max_length=32)
    description: str | None = None
    service_vlan: int = Field(default=2918, ge=1, le=4094)
    service_profile_ids: list[int] | None = None
    # PPPoE credentials — pushed to ONU via OLT CLI
    pppoe_username: str | None = Field(default=None, max_length=128)
    pppoe_password: str | None = Field(default=None, max_length=128)
    # WiFi — pushed via ACS; if not provided, auto-generated from customer_name
    wifi_ssid_2g: str | None = Field(default=None, max_length=64)
    wifi_ssid_5g: str | None = Field(default=None, max_length=64)
    wifi_password: str | None = Field(default=None, max_length=64)


class ONUUpdate(BaseModel):
    description: str | None = None
    onu_type: str | None = None


class PPPoEUpdate(BaseModel):
    pppoe_username: str = Field(..., max_length=128)
    pppoe_password: str = Field(..., max_length=128)
    service_vlan: int | None = Field(default=None, ge=1, le=4094)


class WiFiUpdate(BaseModel):
    ssid_2g: str = Field(..., max_length=64)
    ssid_5g: str = Field(..., max_length=64)
    password: str = Field(..., max_length=64)


class ONUResponse(BaseModel):
    id: int
    olt_id: int
    serial_number: str
    customer_id: str
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    frame: int
    slot: int
    port: int
    onu_id: int
    onu_type: str
    description: str | None
    admin_state: AdminState
    oper_state: OperState
    service_vlan: int | None = None
    pppoe_username: str | None = None
    pppoe_password: str | None = None
    wifi_ssid_2g: str | None = None
    wifi_ssid_5g: str | None = None
    wifi_password: str | None = None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class UnregisteredONU(BaseModel):
    serial_number: str
    frame: int
    slot: int
    port: int
    onu_type: str | None = None


class ONUStatusResponse(BaseModel):
    onu_id: int
    serial_number: str
    admin_state: str
    oper_state: str
    rx_power: str | None = None
    distance: str | None = None
    last_down_cause: str | None = None
