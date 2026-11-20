
from typing import Literal

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthProfileData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_years: int | None = Field(default=None, ge=13, le=120)

    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    sleep_quality: Literal[
        "poor", "fair", "good", "excellent"
    ] | None = None

    water_intake_liters: float | None = Field(
        default=None, ge=0, le=20
    )

    activity_level: Literal[
        "sedentary", "light", "moderate", "active", "very_active"
    ] | None = None

    exercise_days_per_week: int | None = Field(
        default=None, ge=0, le=7
    )

    screen_time_hours: float | None = Field(
        default=None, ge=0, le=24
    )

    diet_type: Literal[
        "balanced", "vegetarian", "vegan", "non_vegetarian", "other"
    ] | None = None

    junk_food_frequency: Literal[
        "never", "rarely", "sometimes", "often", "daily"
    ] | None = None

    stress_level: Literal[
        "low", "moderate", "high", "very_high"
    ] | None = None

    health_conditions: list[str] = Field(default_factory=list, max_length=30)
    allergies: list[str] = Field(default_factory=list, max_length=30)
    current_medications: list[str] = Field(default_factory=list, max_length=30)
    health_goals: list[str] = Field(default_factory=list, max_length=20)

    additional_notes: str | None = Field(default=None, max_length=3000)


class HealthProfileResponse(BaseModel):
    profile: HealthProfileData | None
    onboarding_completed: bool
    ai_personalization_consent: bool
    proactive_health_analysis_consent: bool = False
    proactive_wellness_notifications_consent: bool = False


class AIPersonalizationConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ProactiveConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ConsentStatusResponse(BaseModel):
    ai_personalization_consent: bool
    ai_personalization_consent_at: datetime | None = None
    proactive_health_analysis_consent: bool
    proactive_health_analysis_consent_at: datetime | None = None
    proactive_wellness_notifications_consent: bool
    proactive_wellness_notifications_consent_at: datetime | None = None


class OnboardingCompleteResponse(BaseModel):
    message: str
    onboarding_completed: bool
