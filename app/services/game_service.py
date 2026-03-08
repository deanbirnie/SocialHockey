import uuid
from datetime import date, time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Game


async def create_game(
    title: str,
    game_date: date,
    start_time: time,
    end_time: time,
    max_players: int,
    created_by: uuid.UUID,
    db: AsyncSession,
) -> Game:
    game = Game(
        title=title,
        game_date=game_date,
        start_time=start_time,
        end_time=end_time,
        max_players=max_players,
        created_by=created_by,
    )
    db.add(game)
    await db.commit()
    await db.refresh(game)
    return game


async def get_all_games(db: AsyncSession) -> list[Game]:
    result = await db.execute(select(Game).order_by(Game.game_date.asc()))
    return list(result.scalars().all())


async def get_games_by_status(status: str, db: AsyncSession) -> list[Game]:
    result = await db.execute(
        select(Game).where(Game.status == status).order_by(Game.game_date.asc())
    )
    return list(result.scalars().all())


async def get_game(game_id: uuid.UUID, db: AsyncSession) -> Game:
    result = await db.execute(select(Game).where(Game.id == game_id))
    game = result.scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


async def update_game_status(game_id: uuid.UUID, new_status: str, db: AsyncSession) -> Game:
    game = await get_game(game_id, db)
    game.status = new_status
    await db.commit()
    await db.refresh(game)
    return game


async def get_published_games(db: AsyncSession) -> list[Game]:
    result = await db.execute(
        select(Game)
        .where(Game.status == "published")
        .order_by(Game.game_date.asc())
    )
    return list(result.scalars().all())
