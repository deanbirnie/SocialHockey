import io
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models.user import User
from app.services.export_service import build_excel_workbook, build_whatsapp_message
from app.services.game_service import get_game
from app.services.reservation_service import get_game_backups, get_teams
from app.templating import templates

router = APIRouter(prefix="/admin/games", tags=["export"])


@router.get("/{game_id}/export")
async def export_panel(
    game_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    game = await get_game(game_id, db)
    black_team, _unassigned, white_team = await get_teams(game_id, db)
    backups = await get_game_backups(game_id, db)

    message = build_whatsapp_message(game, black_team, white_team, backups)
    wa_url = "https://wa.me/?text=" + urllib.parse.quote(message)

    return templates.TemplateResponse(
        "components/export_panel.html",
        {
            "request": request,
            "game_id": game_id,
            "wa_message": message,
            "wa_url": wa_url,
        },
    )


@router.get("/{game_id}/export/excel")
async def export_excel(
    game_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    game = await get_game(game_id, db)
    black_team, _unassigned, white_team = await get_teams(game_id, db)
    backups = await get_game_backups(game_id, db)

    data = build_excel_workbook(game, black_team, white_team, backups)
    filename = f"teams_{game.game_date.strftime('%Y-%m-%d')}.xlsx"

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
