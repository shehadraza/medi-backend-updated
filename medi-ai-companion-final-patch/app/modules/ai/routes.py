from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.ai.context_service import get_personalization_status
from app.modules.ai.schemas import (
    AIChatResponse,
    AIRequest,
    AIFeedbackRequest,
    ContextStatusResponse,
    ConversationListResponse,
    ConversationResponse,
    FeedbackResponse,
    WeeklyMedicationInsightResponse,
    WeeklyHealthInsightResponse,
    DailyGuidanceRequest,
    DailyGuidanceResponse,
)
from app.modules.ai.weekly_insights import get_weekly_medication_insight
from app.modules.ai.weekly_health_insights import get_weekly_health_insight
from app.modules.ai.service import (
    chat,
    daily_guidance,
    delete_conversation,
    get_conversation,
    list_conversations,
    submit_feedback,
)


router = APIRouter(prefix="/ai", tags=["AI Health Companion"])


@router.get("/insights/weekly-medication", response_model=WeeklyMedicationInsightResponse)
async def get_weekly_medication_insights(
    timezone_name: str = Query(..., min_length=1, max_length=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User-requested summary; no background analysis or notification is created."""
    return await get_weekly_medication_insight(
        db,
        str(current_user.id),
        timezone_name=timezone_name,
    )


@router.get("/insights/weekly-health", response_model=WeeklyHealthInsightResponse)
async def get_weekly_health_insights(
    timezone_name: str = Query(..., min_length=1, max_length=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User-requested descriptive trends from the previous seven complete local days."""
    return await get_weekly_health_insight(
        db,
        str(current_user.id),
        timezone_name=timezone_name,
    )


@router.post("/guidance/daily", response_model=DailyGuidanceResponse)
async def post_daily_guidance(
    payload: DailyGuidanceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate daily guidance on demand; no conversation is persisted."""
    return await daily_guidance(
        db,
        str(current_user.id),
        locale=payload.locale,
    )


@router.post("/chat", response_model=AIChatResponse)
async def post_chat(
    payload: AIRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await chat(db, str(current_user.id), payload)


@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_conversations(db, str(current_user.id), limit=limit, offset=offset)


@router.get("/context", response_model=ContextStatusResponse)
async def get_ai_context_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        enabled = await get_personalization_status(db, str(current_user.id))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Personalization status is temporarily unavailable.") from exc
    return {
        "personalization_enabled": enabled,
        "message": (
            "Health-profile, daily check-in, medication, prescription, reminder, and adherence context may be used for AI responses with your consent. Conversation history is included only when explicitly requested in a chat request."
            if enabled else
            "Health-profile, daily check-in, medication, prescription, reminder, and adherence context is not used. Conversation history is included only when explicitly requested in a chat request. MEDI can provide general assistance."
        ),
    }


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_history(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_conversation(
        db, str(current_user.id), conversation_id, limit=limit, offset=offset,
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_conversation(db, str(current_user.id), conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/messages/{message_id}/feedback", response_model=FeedbackResponse)
async def post_feedback(
    message_id: str,
    payload: AIFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await submit_feedback(
        db, str(current_user.id), message_id, payload.rating, payload.comment,
    )
