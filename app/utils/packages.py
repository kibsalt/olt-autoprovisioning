"""GPON bandwidth package definitions."""
from fastapi import HTTPException, status

PACKAGE_MAP: dict[str, int] = {
    "GPON-5M":    5120,
    "GPON-10M":   10240,
    "GPON-20M":   20480,
    "GPON-35M":   35840,
    "GPON-50M":   51200,
    "GPON-100M":  102400,
    "GPON-200M":  204800,
    "GPON-1000M": 1024000,
}
TCONT_TYPE = 3  # Type 3: assured + best-effort

def resolve_package(package_id: str) -> tuple[int, int]:
    """Return (bandwidth_kbps, tcont_type). Raises 400 for unknown package."""
    kbps = PACKAGE_MAP.get(package_id)
    if kbps is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown package '{package_id}'. Valid: {list(PACKAGE_MAP)}",
        )
    return kbps, TCONT_TYPE

def kbps_to_profile_name(kbps: int) -> str:
    """Map kbps to nearest OLT T-CONT profile name (Fix_XM)."""
    mbps = kbps // 1024
    return f"Fix_{mbps}M"
