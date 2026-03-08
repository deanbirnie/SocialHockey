import uuid
from datetime import date, time

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin, require_super_admin
from app.models.reservation import Reservation
from app.models.user import User
from app.services import game_service, reservation_service, user_service
from app.templating import templates

router = APIRouter(prefix="/admin")


@router.get("/dashboard")
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    all_games = await game_service.get_all_games(db)
    return templates.TemplateResponse(
        "pages/admin/dashboard.html",
        {
            "request": request,
            "user": user,
            "published": [g for g in all_games if g.status == "published"],
            "draft": [g for g in all_games if g.status == "draft"],
            "completed": [g for g in all_games if g.status == "completed"],
            "cancelled": [g for g in all_games if g.status == "cancelled"],
        },
    )


@router.get("/games/new")
async def game_new(
    request: Request,
    user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "pages/admin/game_new.html", {"request": request, "user": user}
    )


@router.post("/games")
async def game_create(
    title: str = Form(...),
    game_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    max_players: int = Form(24),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await game_service.create_game(
        title=title,
        game_date=date.fromisoformat(game_date),
        start_time=time.fromisoformat(start_time),
        end_time=time.fromisoformat(end_time),
        max_players=max_players,
        created_by=user.id,
        db=db,
    )
    return RedirectResponse("/admin/dashboard", status_code=303)


@router.post("/games/{game_id}/publish")
async def game_publish(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    game = await game_service.update_game_status(game_id, "published", db)
    return templates.TemplateResponse(
        "components/game_card.html",
        {"request": request, "user": user, "game": game},
    )


@router.post("/games/{game_id}/cancel")
async def game_cancel(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    game = await game_service.update_game_status(game_id, "cancelled", db)
    return templates.TemplateResponse(
        "components/game_card.html",
        {"request": request, "user": user, "game": game},
    )


# ---------------------------------------------------------------------------
# Game management page (team assignment)
# ---------------------------------------------------------------------------


def _team_ctx(request, user, game_id, black_team, unassigned, white_team) -> dict:
    return {
        "request": request,
        "user": user,
        "game_id": game_id,
        "black_team": black_team,
        "unassigned": unassigned,
        "white_team": white_team,
    }


async def _full_manage_ctx(
    request: Request,
    user: User,
    game_id: uuid.UUID,
    db: AsyncSession,
    clear_search: bool = False,
) -> dict:
    """Context for both the team-assignment grid and the admin roster section."""
    game = await game_service.get_game(game_id, db)
    black_team, unassigned, white_team = await reservation_service.get_teams(game_id, db)
    backups = await reservation_service.get_game_backups(game_id, db)
    # Derive full ordered player list from the already-fetched team data.
    players = sorted(black_team + unassigned + white_team, key=lambda r: r.position)
    return {
        "request": request,
        "user": user,
        "game": game,
        "game_id": game_id,
        "black_team": black_team,
        "unassigned": unassigned,
        "white_team": white_team,
        "players": players,
        "backups": backups,
        "max_players": game.max_players,
        "available_spots": game.max_players - len(players),
        "clear_search": clear_search,
    }


@router.get("/games/{game_id}")
async def game_manage(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    ctx = await _full_manage_ctx(request, user, game_id, db)
    return templates.TemplateResponse("pages/admin/game_manage.html", ctx)


@router.post("/games/{game_id}/update-teams")
async def update_teams(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    form = await request.form()
    black_ids = form.getlist("team-black[]")
    white_ids = form.getlist("team-white[]")
    await reservation_service.update_team_assignments(game_id, black_ids, white_ids, db)
    return Response(status_code=204)


@router.post("/games/{game_id}/random-teams")
async def random_teams(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    black_team, unassigned, white_team = await reservation_service.random_assign_teams(
        game_id, db
    )
    return templates.TemplateResponse(
        "components/team_lists.html",
        _team_ctx(request, user, game_id, black_team, unassigned, white_team),
    )


@router.post("/games/{game_id}/clear-teams")
async def clear_teams(
    request: Request,
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await reservation_service.clear_team_assignments(game_id, db)
    black_team, unassigned, white_team = await reservation_service.get_teams(game_id, db)
    return templates.TemplateResponse(
        "components/team_lists.html",
        _team_ctx(request, user, game_id, black_team, unassigned, white_team),
    )


# ---------------------------------------------------------------------------
# Admin player management
# ---------------------------------------------------------------------------


@router.post("/games/{game_id}/remove-player/{user_id}")
async def remove_player(
    request: Request,
    game_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await reservation_service.admin_remove_player(game_id, user_id, db)
    ctx = await _full_manage_ctx(request, user, game_id, db)
    return templates.TemplateResponse("components/admin_action_response.html", ctx)


@router.post("/games/{game_id}/add-player")
async def add_player(
    request: Request,
    game_id: uuid.UUID,
    user_id: uuid.UUID = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await reservation_service.admin_add_player(game_id, user_id, db)
    ctx = await _full_manage_ctx(request, user, game_id, db, clear_search=True)
    return templates.TemplateResponse("components/admin_action_response.html", ctx)


@router.get("/games/{game_id}/search-players")
async def search_players(
    request: Request,
    game_id: uuid.UUID,
    q: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    query = q.strip()
    users: list[User] = []
    if len(query) >= 2:
        # Exclude players already in the game.
        existing_result = await db.execute(
            select(Reservation.user_id).where(Reservation.game_id == game_id)
        )
        existing_ids = set(existing_result.scalars().all())
        all_matches = await reservation_service.search_users(query, db)
        users = [u for u in all_matches if u.id not in existing_ids]

    return templates.TemplateResponse(
        "components/player_search_results.html",
        {"request": request, "users": users, "game_id": game_id, "query": query},
    )


@router.post("/games/{game_id}/move-to-backup/{user_id}")
async def move_player_to_backup(
    request: Request,
    game_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await reservation_service.move_to_backup(game_id, user_id, db)
    ctx = await _full_manage_ctx(request, user, game_id, db)
    return templates.TemplateResponse("components/admin_action_response.html", ctx)


@router.post("/games/{game_id}/move-to-main/{user_id}")
async def move_player_to_main(
    request: Request,
    game_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await reservation_service.move_to_main(game_id, user_id, db)
    ctx = await _full_manage_ctx(request, user, game_id, db)
    return templates.TemplateResponse("components/admin_action_response.html", ctx)


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@router.get("/users")
async def users_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    users = await user_service.get_all_users(db)
    return templates.TemplateResponse(
        "pages/admin/users.html",
        {"request": request, "user": user, "users": users},
    )


@router.post("/users/{user_id}/make-admin")
async def make_admin(
    request: Request,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot modify your own role")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role != "player":
        raise HTTPException(status_code=400, detail="User is not a player")
    updated = await user_service.set_role(user_id, "admin", db)
    return templates.TemplateResponse(
        "components/user_row.html",
        {"request": request, "user": user, "row_user": updated},
    )


@router.post("/users/{user_id}/remove-admin")
async def remove_admin(
    request: Request,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot modify your own role")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role != "admin":
        raise HTTPException(status_code=400, detail="User is not an admin")
    updated = await user_service.set_role(user_id, "player", db)
    return templates.TemplateResponse(
        "components/user_row.html",
        {"request": request, "user": user, "row_user": updated},
    )


@router.post("/games/{game_id}/complete")
async def complete_game(
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    await reservation_service.mark_game_completed(game_id, db)
    return Response(status_code=200, headers={"HX-Redirect": "/admin/dashboard"})
