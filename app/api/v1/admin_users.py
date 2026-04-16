"""Admin user management endpoints — JWT + admin role required."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db, require_admin
from app.models.alarm import Technician
from app.models.user import User, UserRole
from app.services.auth_service import hash_password

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Request / Response schemas ────────────────────────────────────────────────

class UserOut(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    active: bool
    technician_id: int | None
    technician_name: str | None
    last_ticket_at: str | None = None

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: UserRole
    email: str | None = None
    # Technician fields (used when role == TECHNICIAN and no existing technician_id)
    technician_id: int | None = None  # link to existing technician record
    # New technician details (ignored for ADMIN role)
    tech_name: str | None = None
    tech_phone: str | None = None
    tech_zone: str | None = None


class UpdateUserRequest(BaseModel):
    email: str | None = None
    role: UserRole | None = None
    active: bool | None = None
    # Linked technician profile fields
    tech_name: str | None = None
    tech_phone: str | None = None
    tech_zone: str | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str


def _user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
        "active": user.active,
        "technician_id": user.technician_id,
        "technician_name": user.technician.name if user.technician else None,
        "last_ticket_at": user.last_ticket_at.isoformat() if user.last_ticket_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """List all users."""
    result = await db.execute(
        select(User).options(selectinload(User.technician)).order_by(User.username)
    )
    users = result.scalars().all()
    return [_user_out(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Create a new user. If role is TECHNICIAN, creates/links a Technician record."""
    # Check username uniqueness
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' already exists",
        )

    # Check email uniqueness if provided
    if body.email:
        existing_email = await db.execute(select(User).where(User.email == body.email))
        if existing_email.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{body.email}' already in use",
            )

    tech_id = body.technician_id

    if body.role == UserRole.TECHNICIAN:
        if tech_id is None:
            # Create a new Technician record
            if not body.tech_name:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="tech_name is required when creating a new technician user without technician_id",
                )
            tech = Technician(
                name=body.tech_name,
                phone=body.tech_phone,
                zone=body.tech_zone,
                email=body.email,
                active=True,
            )
            db.add(tech)
            await db.flush()
            tech_id = tech.id
        else:
            # Verify the linked technician exists
            tech_result = await db.execute(select(Technician).where(Technician.id == tech_id))
            if not tech_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Technician with id={tech_id} not found",
                )

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
        technician_id=tech_id,
        active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    # Load relationship
    result = await db.execute(
        select(User).options(selectinload(User.technician)).where(User.id == user.id)
    )
    user = result.scalar_one()
    return _user_out(user)


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Update user attributes. Also updates the linked Technician record if fields are provided."""
    result = await db.execute(
        select(User).options(selectinload(User.technician)).where(User.id == user_id)
    )
    user: User | None = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.email is not None:
        # Check uniqueness excluding this user
        existing_email = await db.execute(
            select(User).where(User.email == body.email, User.id != user_id)
        )
        if existing_email.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{body.email}' already in use",
            )
        user.email = body.email

    if body.role is not None:
        user.role = body.role

    if body.active is not None:
        user.active = body.active

    # Update linked technician profile if provided
    if user.technician and (body.tech_name or body.tech_phone or body.tech_zone):
        if body.tech_name:
            user.technician.name = body.tech_name
        if body.tech_phone:
            user.technician.phone = body.tech_phone
        if body.tech_zone:
            user.technician.zone = body.tech_zone

    await db.flush()

    result = await db.execute(
        select(User).options(selectinload(User.technician)).where(User.id == user_id)
    )
    user = result.scalar_one()
    return _user_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    """Soft-delete (deactivate) a user. Cannot deactivate yourself."""
    if admin.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user: User | None = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.active = False
    await db.flush()


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Admin resets another user's password."""
    result = await db.execute(select(User).where(User.id == user_id))
    user: User | None = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )
    user.hashed_password = hash_password(body.new_password)
    await db.flush()
