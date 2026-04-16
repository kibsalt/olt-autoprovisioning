"""Authentication endpoints — no X-API-Key required."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.auth_service import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Request / Response schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str
    user_id: int


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class MeResponse(BaseModel):
    user_id: int
    username: str
    email: str | None
    role: str
    active: bool
    technician_id: int | None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with username/password, return JWT."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.technician))
        .where(User.username == body.username)
    )
    user: User | None = result.scalar_one_or_none()

    if not user or not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_token(user.id, user.username, user.role.value)
    display_name = user.username
    if user.technician:
        display_name = user.technician.name

    return LoginResponse(
        access_token=token,
        role=user.role.value,
        name=display_name,
        user_id=user.id,
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the authenticated user's own password."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )
    current_user.hashed_password = hash_password(body.new_password)
    await db.flush()


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's info."""
    return MeResponse(
        user_id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        role=current_user.role.value,
        active=current_user.active,
        technician_id=current_user.technician_id,
    )
