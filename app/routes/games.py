import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_required
from app.models.user import User
from app.services import game_service, reservation_service
from app.templating import templates

router = APIRouter(prefix="/games")


@router.get("")
async def game_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    games = await game_service.get_published_games(db)
    games_with_counts = [
        (game, await reservation_service.get_available_count(game.id, db))
        for game in games
    ]
    return templates.TemplateResponse(
        "pages/games/list.html",
        {"request": request, "user": user, "games_with_counts": games_with_counts},
    )


@router.get("/{game_id}")
async def game_detail(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_required),
):
    game = await game_service.get_game(game_id, db)
    players = await reservation_service.get_game_players(game_id, db)
    backups = await reservation_service.get_game_backups(game_id, db)
    user_reservation = await reservation_service.get_user_reservation(game_id, user.id, db)
    available_count = await reservation_service.get_available_count(game_id, db)

    return templates.TemplateResponse(
        "pages/games/detail.html",
        {
            "request": request,
            "user": user,
            "game": game,
            "players": players,
            "backups": backups,
            "max_players": game.max_players,
            "user_reservation": user_reservation,
            "available_count": available_count,
            "game_id": game_id,
        },
    )
