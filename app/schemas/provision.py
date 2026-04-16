"""BSS-facing flat provisioning schemas."""
from pydantic import BaseModel, Field


class ProvisionRequest(BaseModel):
    customer_id: str = Field(..., max_length=64)
    customer_name: str = Field(..., max_length=256)
    customer_phone: str | None = Field(default=None, max_length=32)
    customer_email: str | None = Field(default=None, max_length=256)
    onu_serial_number: str = Field(..., max_length=16)
    onu_model: str = Field(default="F660", max_length=32)
    olt_id: str = Field(..., description="OLT name, e.g. OLT-NBI-01")
    package_id: str = Field(..., description="e.g. GPON-35M")
    service_vlan: int = Field(..., ge=1, le=4094)
    oam_vlan: int = Field(default=1450, ge=1, le=4094)
    svlan: int | None = Field(default=None, ge=1, le=4094)
    pppoe_username: str | None = Field(default=None, max_length=64)
    pppoe_password: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    # BSS service identifier — passed to ACS SOAP ProvisionCustomer call
    service_id: str | None = Field(default=None, max_length=100)
    # Pre-set WiFi credentials — if provided, used as-is instead of auto-generating
    wifi_ssid_2g: str | None = Field(default=None, max_length=64)
    wifi_ssid_5g: str | None = Field(default=None, max_length=64)
    wifi_password: str | None = Field(default=None, max_length=64)
    # Optional: if the caller already knows the port, skip the discovery scan
    known_frame: int | None = Field(default=None)
    known_slot: int | None = Field(default=None)
    known_port: int | None = Field(default=None)


class ProvisionResponse(BaseModel):
    success: bool
    customer_id: str
    onu_db_id: int
    serial_number: str
    olt_name: str
    onu_location: str
    package_id: str
    wifi_ssid_2g: str
    wifi_ssid_5g: str
    phase_state_confirmed: bool
    acs_informed: bool
    notifications_sent: list[str]
    duration_ms: int


class PackageUpdateRequest(BaseModel):
    package_id: str = Field(..., description="e.g. GPON-100M")


class DeprovisionRequest(BaseModel):
    customer_id: str
