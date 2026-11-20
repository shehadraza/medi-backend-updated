from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field

from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.core.config import settings
from app.models.user import User

from app.modules.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    UserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
)

from app.modules.auth.service import (
    register_user,
    authenticate_user,
)

from app.modules.auth.session_service import (
    create_user_session,
    revoke_user_session,
    rotate_refresh_token,
)

from app.modules.auth.password_reset_service import (
    create_password_reset_token,
    reset_user_password,
)

from app.modules.auth.email_verification_service import (
    create_email_verification_token,
    verify_email_token,
)

from app.modules.auth.repository import get_user_by_email

from app.modules.auth.rate_limit import (
    enforce_rate_limit,
    client_ip_identity,
)

from app.services.email_service import (
    send_password_reset_email,
    send_email_verification_email,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])

bearer_scheme = HTTPBearer(auto_error=False)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    user = await register_user(
        db,
        data.full_name,
        str(data.email),
        data.password,
    )

    raw_token = await create_email_verification_token(
        db,
        user,
    )

    verification_url = (
        f"{settings.FRONTEND_URL.rstrip('/')}"
        f"/verify-email?token={raw_token}"
    )

    background_tasks.add_task(
        send_email_verification_email,
        user.email,
        verification_url,
    )

    return {
        "message": (
            "Account created successfully. "
            "Please check your email to verify your account."
        ),
        "user": UserResponse.model_validate(user),
    }


@router.post("/verify-email")
async def verify_email(
    data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await verify_email_token(
        db,
        data.token,
    )

    return {
        "message": "Email verified successfully. You can now log in.",
        "user": UserResponse.model_validate(user),
    }


@router.post("/resend-verification")
async def resend_verification(
    data: ResendVerificationRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = str(data.email).strip().lower()
    ip = client_ip_identity(request.client.host if request.client else None)
    await enforce_rate_limit(
        db, scope="resend_email_ip", identity=f"{email}|{ip}",
        limit=3, window_seconds=3600,
    )
    await enforce_rate_limit(
        db, scope="resend_ip", identity=ip,
        limit=10, window_seconds=3600,
    )

    user = await get_user_by_email(
        db,
        str(data.email),
    )

    if user and user.is_active and not user.is_verified:
        raw_token = await create_email_verification_token(
            db,
            user,
        )

        verification_url = (
            f"{settings.FRONTEND_URL.rstrip('/')}"
            f"/verify-email?token={raw_token}"
        )

        background_tasks.add_task(
            send_email_verification_email,
            user.email,
            verification_url,
        )

    return {
        "message": (
            "If an unverified account exists, "
            "a new verification email will be sent."
        )
    }


@router.post("/login")
async def login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = str(data.email).strip().lower()
    ip = client_ip_identity(request.client.host if request.client else None)
    await enforce_rate_limit(
        db, scope="login_email_ip", identity=f"{email}|{ip}",
        limit=10, window_seconds=900,
    )
    await enforce_rate_limit(
        db, scope="login_ip", identity=ip,
        limit=40, window_seconds=900,
    )

    user = await authenticate_user(
        db,
        str(data.email),
        data.password,
    )

    tokens = await create_user_session(
        db,
        user.id,
    )

    return {
        "message": "Login successful.",
        "user": UserResponse.model_validate(user),
        "tokens": tokens,
    }


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return current_user


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    revoked = await revoke_user_session(
        db,
        credentials.credentials,
    )

    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        )

    return {
        "message": "Logout successful.",
    }


@router.post("/refresh")
async def refresh_tokens(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    tokens = await rotate_refresh_token(
        db,
        data.refresh_token,
    )

    if tokens is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    return {
        "message": "Tokens refreshed successfully.",
        "tokens": tokens,
    }


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = str(data.email).strip().lower()
    ip = client_ip_identity(request.client.host if request.client else None)
    await enforce_rate_limit(
        db, scope="forgot_email_ip", identity=f"{email}|{ip}",
        limit=3, window_seconds=3600,
    )
    await enforce_rate_limit(
        db, scope="forgot_ip", identity=ip,
        limit=10, window_seconds=3600,
    )

    user = await get_user_by_email(
        db,
        data.email,
    )

    if user and user.is_active:
        raw_token = await create_password_reset_token(
            db,
            user.id,
        )

        reset_url = (
            f"{settings.FRONTEND_URL.rstrip('/')}"
            f"/reset-password?token={raw_token}"
        )

        background_tasks.add_task(
            send_password_reset_email,
            user.email,
            reset_url,
        )

    return {
        "message": (
            "If the account exists, "
            "a password reset link will be sent."
        )
    }


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    success = await reset_user_password(
        db,
        data.token,
        data.new_password,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or already used reset token.",
        )

    return {
        "message": "Password reset successful. Please log in again."
    }
