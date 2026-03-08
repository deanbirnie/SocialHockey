import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_required
from app.models.user import User
from app.services import game_service, reservation_service
from app.templating import templates

router = APIRouter()


async def _lists_context(game_id: uuid.UUID, user: User, db: AsyncSession) -> dict:
    """Build the template context needed to re-render the game-lists partial."""
    players = await reservation_service.get_game_players(game_id, db)
    backups = await reservation_service.get_game_backups(game_id, db)
    user_reservation = await reservation_service.get_user_reservation(game_id, user.id, db)
    available_count = await reservation_service.get_available_count(game_id, db)
    game = await game_service.get_game(game_id, db)
    return {
        "players": players,
        "backups": backups,
        "max_players": game.max_players,
        "user_reservation": user_reservation,
        "available_count": available_count,
        "game_id": game_id,
    }


@router.post("/games/{game_id}/reserve")
async def reserve(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    await reservation_service.reserve_spot(game_id, user.id, db)
    ctx = await _lists_context(game_id, user, db)
    return templates.TemplateResponse(
        "components/game_lists.html", {"request": request, "user": user, **ctx}
    )


@router.post("/games/{game_id}/cancel")
async def cancel(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    await reservation_service.cancel_reservation(game_id, user.id, db)
    ctx = await _lists_context(game_id, user, db)
    return templates.TemplateResponse(
        "components/game_lists.html", {"request": request, "user": user, **ctx}
    )
