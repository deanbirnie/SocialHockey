import random
import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.game import Game
from app.models.reservation import Reservation
from app.models.user import User


async def get_game_players(game_id: uuid.UUID, db: AsyncSession) -> list[Reservation]:
    """Main list (is_backup=False), ordered by position, with user loaded."""
    result = await db.execute(
        select(Reservation)
        .options(selectinload(Reservation.user))
        .where(Reservation.game_id == game_id, Reservation.is_backup == False)  # noqa: E712
        .order_by(Reservation.position.asc())
    )
    return list(result.scalars().all())


async def get_game_backups(game_id: uuid.UUID, db: AsyncSession) -> list[Reservation]:
    """Backup queue (is_backup=True), ordered by position, with user loaded."""
    result = await db.execute(
        select(Reservation)
        .options(selectinload(Reservation.user))
        .where(Reservation.game_id == game_id, Reservation.is_backup == True)  # noqa: E712
        .order_by(Reservation.position.asc())
    )
    return list(result.scalars().all())


async def get_available_count(game_id: uuid.UUID, db: AsyncSession) -> int:
    """Number of unfilled main-list spots."""
    max_players_result = await db.execute(
        select(Game.max_players).where(Game.id == game_id)
    )
    max_players = max_players_result.scalar()
    if max_players is None:
        return 0

    main_count_result = await db.execute(
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.game_id == game_id, Reservation.is_backup == False)  # noqa: E712
    )
    main_count = main_count_result.scalar() or 0
    return max(0, max_players - main_count)


async def get_user_reservation(
    game_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> Reservation | None:
    result = await db.execute(
        select(Reservation).where(
            Reservation.game_id == game_id,
            Reservation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def reserve_spot(
    game_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> Reservation:
    # Lock the game row — only one transaction can proceed per game at a time.
    result = await db.execute(
        select(Game).where(Game.id == game_id).with_for_update()
    )
    game = result.scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.status != "published":
        raise HTTPException(status_code=400, detail="Game is not open for reservations")

    # Pre-check: user may already be reserved (e.g. double-click).
    existing = await get_user_reservation(game_id, user_id, db)
    if existing:
        return existing

    # Count current main-list spots to decide placement.
    main_count_result = await db.execute(
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.game_id == game_id, Reservation.is_backup == False)  # noqa: E712
    )
    main_count = main_count_result.scalar() or 0

    if main_count < game.max_players:
        position = main_count + 1
        is_backup = False
    else:
        max_pos_result = await db.execute(
            select(func.max(Reservation.position)).where(Reservation.game_id == game_id)
        )
        max_pos = max_pos_result.scalar() or 0
        position = max_pos + 1
        is_backup = True

    reservation = Reservation(
        game_id=game_id,
        user_id=user_id,
        position=position,
        is_backup=is_backup,
    )
    db.add(reservation)

    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        # Race condition: another request squeezed in; surface existing reservation.
        await db.rollback()
        existing = await get_user_reservation(game_id, user_id, db)
        if existing:
            return existing
        raise

    return reservation


async def cancel_reservation(
    game_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> None:
    # Lock game row for the duration of this operation.
    await db.execute(select(Game).where(Game.id == game_id).with_for_update())

    result = await db.execute(
        select(Reservation).where(
            Reservation.game_id == game_id,
            Reservation.user_id == user_id,
        )
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        return

    vacated_position = reservation.position
    was_main = not reservation.is_backup

    await db.delete(reservation)
    await db.flush()  # Free the position before promoting a backup

    if was_main:
        # Promote the first queued backup player to the vacated main spot.
        result = await db.execute(
            select(Reservation)
            .where(Reservation.game_id == game_id, Reservation.is_backup == True)  # noqa: E712
            .order_by(Reservation.position.asc())
            .limit(1)
        )
        first_backup = result.scalar_one_or_none()
        if first_backup:
            first_backup.is_backup = False
            first_backup.position = vacated_position

    await db.commit()


# ---------------------------------------------------------------------------
# Team assignment helpers
# ---------------------------------------------------------------------------


async def get_teams(
    game_id: uuid.UUID, db: AsyncSession
) -> tuple[list[Reservation], list[Reservation], list[Reservation]]:
    """Returns (black_team, unassigned, white_team) — main list only, users loaded."""
    result = await db.execute(
        select(Reservation)
        .options(selectinload(Reservation.user))
        .where(Reservation.game_id == game_id, Reservation.is_backup == False)  # noqa: E712
        .order_by(Reservation.position.asc())
    )
    all_main = list(result.scalars().all())
    return (
        [r for r in all_main if r.team == "black"],
        [r for r in all_main if r.team is None],
        [r for r in all_main if r.team == "white"],
    )


async def update_team_assignments(
    game_id: uuid.UUID,
    black_ids: list[str],
    white_ids: list[str],
    db: AsyncSession,
) -> None:
    """Set team for each main-list reservation based on the supplied user-ID lists."""
    black_set = {uuid.UUID(uid) for uid in black_ids if uid}
    white_set = {uuid.UUID(uid) for uid in white_ids if uid}

    result = await db.execute(
        select(Reservation).where(
            Reservation.game_id == game_id,
            Reservation.is_backup == False,  # noqa: E712
        )
    )
    for r in result.scalars().all():
        if r.user_id in black_set:
            r.team = "black"
        elif r.user_id in white_set:
            r.team = "white"
        else:
            r.team = None

    await db.commit()


async def random_assign_teams(
    game_id: uuid.UUID, db: AsyncSession
) -> tuple[list[Reservation], list[Reservation], list[Reservation]]:
    """Randomly split main-list players into black and white teams."""
    result = await db.execute(
        select(Reservation).where(
            Reservation.game_id == game_id,
            Reservation.is_backup == False,  # noqa: E712
        )
    )
    reservations = list(result.scalars().all())
    random.shuffle(reservations)

    # Ceiling division: odd player goes to black
    half = (len(reservations) + 1) // 2
    for i, r in enumerate(reservations):
        r.team = "black" if i < half else "white"

    await db.commit()
    return await get_teams(game_id, db)


async def clear_team_assignments(game_id: uuid.UUID, db: AsyncSession) -> None:
    """Set team=NULL for every reservation in this game."""
    result = await db.execute(
        select(Reservation).where(Reservation.game_id == game_id)
    )
    for r in result.scalars().all():
        r.team = None
    await db.commit()


# ---------------------------------------------------------------------------
# Admin player management
# ---------------------------------------------------------------------------


async def admin_remove_player(
    game_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> None:
    """Remove a player from the game; promote first backup if removed from main list."""
    await db.execute(select(Game).where(Game.id == game_id).with_for_update())

    result = await db.execute(
        select(Reservation).where(
            Reservation.game_id == game_id,
            Reservation.user_id == user_id,
        )
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        return

    vacated_position = reservation.position
    was_main = not reservation.is_backup

    await db.delete(reservation)
    await db.flush()

    if was_main:
        result = await db.execute(
            select(Reservation)
            .where(Reservation.game_id == game_id, Reservation.is_backup == True)  # noqa: E712
            .order_by(Reservation.position.asc())
            .limit(1)
        )
        first_backup = result.scalar_one_or_none()
        if first_backup:
            first_backup.is_backup = False
            first_backup.position = vacated_position

    await db.commit()


async def admin_add_player(
    game_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> Reservation:
    """Admin manually adds a player. Raises 400 if already reserved."""
    result = await db.execute(select(Game).where(Game.id == game_id).with_for_update())
    game = result.scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")

    existing = await get_user_reservation(game_id, user_id, db)
    if existing:
        raise HTTPException(status_code=400, detail="Player is already in this game")

    main_count_result = await db.execute(
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.game_id == game_id, Reservation.is_backup == False)  # noqa: E712
    )
    main_count = main_count_result.scalar() or 0

    if main_count < game.max_players:
        max_main_pos_result = await db.execute(
            select(func.max(Reservation.position)).where(
                Reservation.game_id == game_id,
                Reservation.is_backup == False,  # noqa: E712
            )
        )
        position = (max_main_pos_result.scalar() or 0) + 1
        is_backup = False
    else:
        max_pos_result = await db.execute(
            select(func.max(Reservation.position)).where(Reservation.game_id == game_id)
        )
        position = (max_pos_result.scalar() or 0) + 1
        is_backup = True

    reservation = Reservation(
        game_id=game_id,
        user_id=user_id,
        position=position,
        is_backup=is_backup,
    )
    db.add(reservation)
    await db.commit()
    return reservation


async def move_to_backup(
    game_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> None:
    """Move a main-list player to end of backup queue; promote first backup to fill the gap."""
    await db.execute(select(Game).where(Game.id == game_id).with_for_update())

    result = await db.execute(
        select(Reservation).where(
            Reservation.game_id == game_id,
            Reservation.user_id == user_id,
        )
    )
    reservation = result.scalar_one_or_none()
    if reservation is None or reservation.is_backup:
        return

    old_position = reservation.position

    # Find first backup to promote (load before modifying anything).
    backup_result = await db.execute(
        select(Reservation)
        .where(Reservation.game_id == game_id, Reservation.is_backup == True)  # noqa: E712
        .order_by(Reservation.position.asc())
        .limit(1)
    )
    first_backup = backup_result.scalar_one_or_none()

    # New backup slot = strictly after every existing position.
    max_pos_result = await db.execute(
        select(func.max(Reservation.position)).where(Reservation.game_id == game_id)
    )
    new_backup_pos = (max_pos_result.scalar() or 0) + 1

    reservation.is_backup = True
    reservation.position = new_backup_pos
    await db.flush()  # Frees old_position before assigning it to first_backup.

    if first_backup:
        first_backup.is_backup = False
        first_backup.position = old_position

    await db.commit()


async def move_to_main(
    game_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> None:
    """Move a backup player onto the main list if a spot is available."""
    result = await db.execute(select(Game).where(Game.id == game_id).with_for_update())
    game = result.scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")

    res_result = await db.execute(
        select(Reservation).where(
            Reservation.game_id == game_id,
            Reservation.user_id == user_id,
        )
    )
    reservation = res_result.scalar_one_or_none()
    if reservation is None or not reservation.is_backup:
        return

    main_count_result = await db.execute(
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.game_id == game_id, Reservation.is_backup == False)  # noqa: E712
    )
    if (main_count_result.scalar() or 0) >= game.max_players:
        raise HTTPException(status_code=400, detail="Main list is full")

    max_pos_result = await db.execute(
        select(func.max(Reservation.position)).where(Reservation.game_id == game_id)
    )
    # Assign a position strictly higher than everything so it's unique.
    reservation.is_backup = False
    reservation.position = (max_pos_result.scalar() or 0) + 1
    await db.commit()


async def mark_game_completed(game_id: uuid.UUID, db: AsyncSession) -> None:
    """Set the game status to 'completed'."""
    result = await db.execute(select(Game).where(Game.id == game_id))
    game = result.scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    game.status = "completed"
    await db.commit()


async def search_users(query: str, db: AsyncSession) -> list[User]:
    """Search users by first or last name (case-insensitive ILIKE), limit 20."""
    result = await db.execute(
        select(User)
        .where(
            or_(
                User.first_name.ilike(f"%{query}%"),
                User.last_name.ilike(f"%{query}%"),
            )
        )
        .order_by(User.last_name.asc(), User.first_name.asc())
        .limit(20)
    )
    return list(result.scalars().all())
