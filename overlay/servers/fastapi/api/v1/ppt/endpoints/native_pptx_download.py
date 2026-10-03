# Native PPTX authenticated temporary downloads. SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import os
import re
from urllib.parse import quote
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.v1.auth.context import get_current_owner_id
from services.native_pptx_downloads import NativeDownloadNotFound, is_native_download_path, read_native_download
from utils.get_env import get_app_data_directory_env

NATIVE_DOWNLOAD_ROUTER = APIRouter(tags=["Native PPTX downloads"])
PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def require_native_browser_owner(request: Request) -> uuid.UUID:
    owner = get_current_owner_id()
    principal = getattr(request.state, "auth_principal", None)
    if owner is None or principal is None or principal.method != "jwt" or principal.user_id != owner:
        raise HTTPException(401, "A signed-in browser session is required for native downloads")
    return owner


class NativeProtectedAppDataFiles(StaticFiles):
    """Native files can only be served by the earlier authenticated TTL handler."""
    def lookup_path(self, path: str):
        full_path, info = super().lookup_path(path)
        if info is not None:
            for directory in self.all_directories:
                relative = os.path.relpath(full_path, os.path.realpath(directory))
                if is_native_download_path("/app_data/" + relative.replace(os.sep, "/")):
                    return "", None
        return full_path, info

    async def get_response(self, path: str, scope):
        if is_native_download_path("/app_data/" + path):
            raise StarletteHTTPException(404)
        return await super().get_response(path, scope)


@NATIVE_DOWNLOAD_ROUTER.api_route("/app_data/exports/users/{owner}/native-pptx/{tail:path}", methods=["GET", "HEAD"])
async def download_native_pptx(request: Request, owner: str, tail: str):
    current_owner = require_native_browser_owner(request)
    match = re.fullmatch(r"([0-9a-f]{32})\.pptx", tail)
    expected = f"/app_data/exports/users/{current_owner}/native-pptx/{tail}"
    if (owner != str(current_owner) or not match or request.scope.get("raw_path") != expected.encode("ascii")
        or request.url.query):
        raise HTTPException(404, "Native download not found")
    root = get_app_data_directory_env()
    if not root:
        raise HTTPException(404, "Native download not found")
    try:
        content, filename = await run_in_threadpool(read_native_download, Path(root), current_owner, match.group(1))
    except NativeDownloadNotFound as exc:
        raise HTTPException(404, "Native download not found") from exc
    return Response(content=content if request.method == "GET" else b"", media_type=PPTX_CONTENT_TYPE, headers={
        "Content-Disposition": f"attachment; filename=\"presentation-native.pptx\"; filename*=UTF-8''{quote(filename, safe='')}",
        "Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff", "Content-Length": str(len(content)),
    })
