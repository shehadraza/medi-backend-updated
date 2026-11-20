
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    email: EmailStr
    is_active: bool
    is_verified: bool
    is_admin: bool
    role: str
    created_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int
    limit: int
    offset: int


class AdminActionResponse(BaseModel):
    message: str
    user: AdminUserResponse
