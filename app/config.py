from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="OLT_")

    # Application
    app_name: str = "JTL OLT Provisioning API"
    debug: bool = False

    # API auth (comma-separated in env var)
    api_keys: str = ""

    @field_validator("api_keys", mode="before")
    @classmethod
    def parse_api_keys(cls, v):
        return v

    @property
    def api_key_list(self) -> list[str]:
        if not self.api_keys:
            return []
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    # Database
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "olt_api"
    db_password: str = "changeme"
    db_name: str = "olt_provisioning"

    # SSH defaults
    ssh_connect_timeout: float = 10.0
    ssh_command_timeout: float = 30.0

    # Encryption key for OLT credentials at rest (Fernet key)
    credential_encryption_key: str = ""

    # ACS configuration (TR-069)
    acs_url: str = "http://197.232.61.253:7547"
    acs_username: str = "ACS"
    acs_password: str = "jtl@acs"
    # GenicACS northbound management API (default port 7557)
    acs_management_url: str = "http://197.232.61.253:7557"

    # SMTP for email notifications
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@jtl.co.ke"
    smtp_use_tls: bool = True

    # Africa's Talking SMS
    at_username: str = ""
    at_api_key: str = ""
    at_sender_id: str = "JTL"
    at_whatsapp_sender: str = ""

    # WiFi SSID prefix
    wifi_ssid_prefix: str = "JTL"

    # Alarm monitoring
    alarm_poll_interval: int = 300   # seconds between polls (default 5 min)
    alarm_rx_minor_threshold: float = -26.0    # dBm — minor warning
    alarm_rx_major_threshold: float = -27.0    # dBm — major
    alarm_rx_critical_threshold: float = -28.0 # dBm — critical

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    workers: int = 4

    @property
    def database_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
