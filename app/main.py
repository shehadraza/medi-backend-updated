
from fastapi import FastAPI

from app.core.config import settings
from app.modules.admin.routes import router as admin_router
from app.modules.auth.routes import router as auth_router
from app.modules.onboarding.routes import router as onboarding_router
from app.modules.prescriptions.routes import router as prescriptions_router
from app.modules.medicines.routes import router as medicines_router
from app.modules.medicines.catalog_routes import (
    public_router as medicine_catalog_router,
    admin_router as admin_medicine_catalog_router,
)
from app.modules.reminders.routes import router as reminders_router
from app.modules.notifications.routes import router as notifications_router
from app.modules.ai.routes import router as ai_router
from app.modules.health.checkin_routes import router as health_checkins_router


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/")
async def root():
    return {
        "message": "MEDI API is running.",
        "version": settings.APP_VERSION,
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "MEDI API",
    }


# Authentication
app.include_router(auth_router)

# User health profile and onboarding
app.include_router(onboarding_router)
app.include_router(health_checkins_router)

# Prescription management
app.include_router(prescriptions_router)

# Personal medicine cabinet
app.include_router(medicines_router)

# Verified medicine catalog
app.include_router(medicine_catalog_router)

# Admin medicine catalog management
app.include_router(admin_medicine_catalog_router)

# Medication reminders
app.include_router(reminders_router)

# Notification inbox
app.include_router(notifications_router)
# Super Admin management
app.include_router(admin_router)

# Authenticated AI Health Companion
app.include_router(ai_router)
