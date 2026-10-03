# Native PPTX beta add-on (2026-10-03). SPDX-License-Identifier: Apache-2.0
"""Authenticated, read-only native export of the stored Standard canvas.

This independent endpoint deliberately does not call the existing HTML exporter,
provider APIs, or any presentation mutation/generation code.
"""

from dataclasses import asdict
import json
from pathlib import Path
import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from starlette.concurrency import run_in_threadpool

from api.v1.auth.context import get_current_owner_id
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from services.database import get_async_session
from utils.get_env import get_app_data_directory_env
from utils.path_helpers import get_resource_path

NATIVE_PPTX_ROUTER = APIRouter(prefix="/presentation", tags=["Native PPTX (beta)"])
PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"



def _builtin_templates_root() -> Path:
    # Match upstream's bundled template layout; no request or config selects it.
    return Path(__file__).absolute().parents[6] / "templates"


def _download_filename(title: str | None) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", title or "presentation").strip("-_")
    return f"{base[:60].rstrip('-_') or 'presentation'}-native.pptx"


def _warning_headers(warnings) -> dict[str, str]:
    # Diagnostics must stay bounded for reverse proxies. Never silently omit a
    # warning: the client receives the full count and an explicit omitted count.
    included = []
    encoded = "[]"
    for warning in warnings:
        candidate = json.dumps([*included, asdict(warning)], ensure_ascii=True)
        if len(candidate) > 4096:
            break
        included.append(asdict(warning))
        encoded = candidate
    return {
        "X-Native-Pptx-Warnings": encoded,
        "X-Native-Pptx-Warning-Count": str(len(warnings)),
        "X-Native-Pptx-Warnings-Truncated": str(len(warnings) - len(included)),
        # Electron and explicitly configured backends can use a separate origin.
        "Access-Control-Expose-Headers": "Content-Disposition, X-Native-Pptx-Warnings, X-Native-Pptx-Warning-Count, X-Native-Pptx-Warnings-Truncated",
    }


@NATIVE_PPTX_ROUTER.post("/{id}/export/native-pptx")
async def export_native_pptx(
    id: uuid.UUID,
    request: Request,
    delivery: Annotated[Literal["bytes", "file"], Body(embed=True)] = "bytes",
    sql_session: AsyncSession = Depends(get_async_session),
):
    # Fail closed even if mounted outside the application's auth middleware.
    owner_id = get_current_owner_id()
    if owner_id is None:
        raise HTTPException(401, "Authentication is required for Native PPTX (beta)")

    if delivery == "file":
        from api.v1.ppt.endpoints.native_pptx_download import require_native_browser_owner
        require_native_browser_owner(request)

    presentation = await sql_session.scalar(
        select(PresentationModel).where(
            PresentationModel.id == id,
            PresentationModel.owner_id == owner_id,
        )
    )
    if presentation is None:
        raise HTTPException(404, "Presentation not found")
    if (
        presentation.generation_mode != "standard"
        or presentation.version != PresentationVersion.V2_STANDARD
    ):
        raise HTTPException(
            422,
            "Native PPTX (beta) requires a Standard canvas presentation; Smart/HTML and legacy presentations are not supported",
        )

    slides = list(await sql_session.scalars(
        select(SlideModel)
        .where(SlideModel.presentation == id, SlideModel.owner_id == owner_id)
        .order_by(SlideModel.index, SlideModel.id)
    ))
    if not slides or len(slides) != presentation.n_slides:
        raise HTTPException(409, "Wait for every slide to finish saving before exporting Native PPTX (beta)")
    for index, slide in enumerate(slides):
        if not isinstance(slide.ui, dict):
            raise HTTPException(422, f"slides[{index}].ui: Native PPTX (beta) requires stored Standard canvas UI")

    # Import the add-on lazily: installing it does not alter legacy export paths.
    from services.native_standard_pptx import export_standard_pptx

    from services.native_pptx_assets import resolve_native_image_assets

    try:
        slide_uis = [slide.ui for slide in slides]
        app_data = get_app_data_directory_env()
        image_assets = await run_in_threadpool(
            resolve_native_image_assets,
            slide_uis,
            owner_id=owner_id,
            app_data_root=Path(app_data) if app_data else None,
            static_root=Path(get_resource_path("static")),
            builtin_templates_root=_builtin_templates_root(),
        )
        result = await run_in_threadpool(
            export_standard_pptx,
            slide_uis,
            image_assets=image_assets,
            title=presentation.title or "Presentation",
            theme=presentation.theme,
            unsupported="error",
        )
    except ValueError as exc:
        # Exporter validation errors include exact paths, useful for fixing a
        # slide rather than silently flattening or dropping unsupported content.
        raise HTTPException(422, str(exc)) from exc

    if delivery == "file":
        from services.native_pptx_downloads import create_native_download, NativeDownloadNotFound
        root = get_app_data_directory_env()
        if not root:
            raise HTTPException(503, "Native download storage is unavailable")
        try:
            download = await run_in_threadpool(create_native_download, Path(root), owner_id,
                                               result.pptx_bytes, presentation.title)
        except NativeDownloadNotFound as exc:
            raise HTTPException(503, "Native download storage is unavailable") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return JSONResponse({**download, "warnings": [asdict(warning) for warning in result.warnings]},
                            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    return Response(
        content=result.pptx_bytes,
        media_type=PPTX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{_download_filename(presentation.title)}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            **_warning_headers(result.warnings),
        },
    )
