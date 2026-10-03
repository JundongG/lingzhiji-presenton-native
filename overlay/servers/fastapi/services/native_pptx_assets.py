# Native PPTX beta add-on (2026-10-03). SPDX-License-Identifier: Apache-2.0
"""Bounded local asset reads for the authenticated Native PPTX endpoint.

Only call with already-owned, stored slide UI. This resolver accepts root-relative
application URLs, never arbitrary filesystem paths or network URLs. It intentionally
narrows upstream asset authorization: no administrator legacy-root fallback and no
arbitrary shared app-data assets. Two pinned Standard template raster references
map to their original bundled source files, never shared app-data copies. Symlinks and hard links are rejected, including directory
components, and file opens use directory descriptors to avoid traversal/TOCTOU.
The pure exporter separately decodes and validates supplied PNG/JPEG bytes.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
import uuid

from api.v1.auth.assets import is_app_data_path_authorized, normalized_app_data_parts
from services.native_standard_pptx import NativeStandardExportError

MAX_ASSETS = 100
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 32 * 1024 * 1024
MAX_NODES = 10000
MAX_DEPTH = 32
_OWNED_IMAGE_ROOTS = frozenset({"images", "uploads", "pptx-to-html", "pptx-to-json"})
_RASTER_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
# Exact public raster references declared by templates/standard/template.json at
# upstream e158a014 (0.9.11-beta). This is a pinned allowlist, not path discovery.
# Never expand it from user-authored UI or the mutable app_data/templates tree.
_BUNDLED_STANDARD_RASTERS = (
    "static/image6-d77d5bd67ea3.png",
    "static/image8-1bc3f07c9b32.png",
)
_BUNDLED_RASTER_LOCATIONS = {
    alias: ("standard", *ref.split("/"))
    for ref in _BUNDLED_STANDARD_RASTERS
    for alias in (ref, f"/app_data/templates/standard/{ref}")
}



def _error(path: str, message: str, code: str = "invalid_image_asset"):
    raise NativeStandardExportError(message, path=path, code=code)


def _image_references(slide_uis: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Walk only rendered canvas element slots, never metadata/prompt dictionaries."""
    refs: dict[str, str] = {}
    nodes = 0

    def elements(items: Any, path: str, depth: int) -> None:
        if not isinstance(items, list):
            _error(path, "Canvas elements must be an array")
        for index, item in enumerate(items):
            element(item, f"{path}[{index}]", depth)

    def element(item: Any, path: str, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            _error(path, "Local image traversal limit exceeded", "export_limit")
        if not isinstance(item, dict):
            _error(path, "Canvas element must be an object")
        kind = item.get("type")
        if not isinstance(kind, str):
            _error(path + ".type", "Canvas element type must be a string")
        if kind == "image":
            ref = item.get("data")
            if not isinstance(ref, str) or not ref:
                _error(path + ".data", "Image requires a local PNG/JPEG asset reference")
            refs.setdefault(ref, path + ".data")
            if len(refs) > MAX_ASSETS:
                _error(path + ".data", f"At most {MAX_ASSETS} image assets are supported", "export_limit")
        elif kind == "container" and item.get("child") is not None:
            element(item["child"], path + ".child", depth + 1)
        elif kind in {"group", "flex", "grid"}:
            key = "elements" if kind == "group" and "children" not in item and "elements" in item else "children"
            elements(item.get(key, []), path + "." + key, depth + 1)

    if not isinstance(slide_uis, (list, tuple)) or not 1 <= len(slide_uis) <= 200:
        _error("slides", "Expected 1–200 stored slide UI objects", "export_limit")
    for index, ui in enumerate(slide_uis):
        path = f"slides[{index}].ui"
        if not isinstance(ui, dict):
            _error(path, "Stored canvas UI must be an object")
        components = ui.get("components", [])
        if not isinstance(components, list):
            _error(path + ".components", "Canvas components must be an array")
        for number, component in enumerate(components):
            cpath = f"{path}.components[{number}]"
            nodes += 1
            if nodes > MAX_NODES:
                _error(cpath, "Local image traversal limit exceeded", "export_limit")
            if not isinstance(component, dict):
                _error(cpath, "Canvas component must be an object")
            elements(component.get("elements", []), cpath + ".elements", 0)
        elements(ui.get("elements", []), path + ".elements", 0)
    return refs


def _asset_location(ref: str, path: str, owner_id: uuid.UUID,
                    app_data_root: Path | None, static_root: Path,
                    builtin_templates_root: Path | None) -> tuple[Path, tuple[str, ...]]:
    if len(ref) > 4096 or ref != ref.strip() or any(ord(char) < 32 or ord(char) == 127 for char in ref):
        _error(path, "Invalid local image reference")
    try:
        url = urlsplit(ref)
    except ValueError:
        _error(path, "Invalid local image reference")
    if url.scheme or url.netloc or url.query or url.fragment:
        _error(path, "Only root-relative local PNG/JPEG asset paths are supported; URLs are not fetched")
    if ref in _BUNDLED_RASTER_LOCATIONS:
        if builtin_templates_root is None:
            _error(path, "Pinned bundled image storage is unavailable")
        parts = _BUNDLED_RASTER_LOCATIONS[ref]
        root = builtin_templates_root
    elif ref.startswith("/static/"):
        # Reuse upstream repeated-decoding/traversal validation on the mount suffix.
        parts = normalized_app_data_parts("/app_data/" + ref[len("/static/"):])
        root = static_root
    elif ref.startswith("/app_data/"):
        parts = normalized_app_data_parts(ref)
        if (not parts or len(parts) < 4 or parts[0] not in _OWNED_IMAGE_ROOTS
            or parts[1] != "users" or parts[2] != str(owner_id)
            or not is_app_data_path_authorized(ref, user_id=owner_id, is_admin=False)):
            _error(path, "Image asset must belong to the current presentation owner")
        if app_data_root is None:
            _error(path, "Local image asset storage is unavailable")
        root = app_data_root
    else:
        _error(path, "Only /static/ or owner-scoped /app_data/ PNG/JPEG assets are supported")
    if not parts or any(any(ord(char) < 32 or ord(char) == 127 for char in part) for part in parts):
        _error(path, "Invalid local image path or traversal")
    if Path(parts[-1]).suffix.lower() not in _RASTER_EXTENSIONS:
        _error(path, "Only local PNG/JPEG image files are supported; SVG and other formats are rejected")
    return root, parts


def _read_beneath(root: Path, parts: tuple[str, ...], path: str, byte_budget: int = MAX_ASSET_BYTES) -> bytes:
    byte_budget = min(byte_budget, MAX_ASSET_BYTES)
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        _error(path, "Safe local image reads are unsupported on this platform")
    if not root.is_absolute() or ".." in root.parts:
        _error(path, "Local image storage must use an absolute trusted directory")
    directory_fd = None
    file_fd = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_fd = os.open(root.anchor, flags)
        # Never follow symlinks, including configured root ancestors.
        for component in (*root.parts[1:], *parts[:-1]):
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _error(path, "Image asset must be a regular, non-linked file")
        if info.st_size <= 0 or info.st_size > byte_budget:
            _error(path, f"Image asset must be nonempty and within the remaining {byte_budget}-byte budget", "export_limit")
        # The bounded read also catches a file that grew after fstat.
        with os.fdopen(file_fd, "rb", closefd=True) as image_file:
            file_fd = None
            data = image_file.read(byte_budget + 1)
        if not data or len(data) > byte_budget:
            _error(path, "Image asset exceeds the allowed byte limit", "export_limit")
        return data
    except OSError:
        _error(path, "Local image asset is missing, unreadable, or linked outside permitted storage")
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def resolve_native_image_assets(slide_uis: Sequence[Mapping[str, Any]], *, owner_id: uuid.UUID,
                                app_data_root: Path | None, static_root: Path,
                                builtin_templates_root: Path | None = None) -> dict[str, bytes]:
    """Load referenced local images only; caller supplies trusted server roots."""
    if not isinstance(owner_id, uuid.UUID):
        _error("slides", "An authenticated owner is required for local image assets")
    refs = _image_references(slide_uis)
    # Validate every reference before any file is opened, including mixed decks.
    locations = {ref: _asset_location(ref, path, owner_id, app_data_root, static_root, builtin_templates_root)
                 for ref, path in refs.items()}
    result: dict[str, bytes] = {}
    total = 0
    for ref, (root, parts) in locations.items():
        data = _read_beneath(root, parts, refs[ref], MAX_TOTAL_ASSET_BYTES - total)
        total += len(data)
        if total > MAX_TOTAL_ASSET_BYTES:
            _error(refs[ref], "Combined image assets exceed the allowed byte limit", "export_limit")
        result[ref] = data
    return result
