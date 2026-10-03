# Native PPTX temporary delivery (2026-10-03). SPDX-License-Identifier: Apache-2.0
"""Private generated-file storage. No access to originals, providers, or credentials."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager, suppress
import hashlib
try:
    import fcntl
except ImportError:  # Preserve the rest of the app on non-POSIX platforms.
    fcntl = None
import hmac
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import unquote
import uuid
from zipfile import ZipFile, BadZipFile

NATIVE_DOWNLOAD_DIRECTORY = "native-pptx"
DOWNLOAD_TTL_SECONDS = 15 * 60
CLEANUP_INTERVAL_SECONDS = 60
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_OWNER_DOWNLOADS = 10
_FILE_ID = re.compile(r"^[0-9a-f]{32}$")
_OWNER = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SCHEMA = "presenton.native-pptx-download.v1"


class NativeDownloadNotFound(ValueError):
    pass


def is_native_download_path(path: str) -> bool:
    """Classify aliases too, so static serving/cloud forwarding never handles them."""
    for _ in range(8):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    parts = path.replace("\\", "/").split("/")
    return "app_data" in parts and "exports" in parts and NATIVE_DOWNLOAD_DIRECTORY in parts


def native_download_filename(title: str | None) -> str:
    value = re.sub(r"[\x00-\x1f\x7f\ud800-\udfff/\\]", "-", str(title or "Presentation"))
    value = re.sub(r"\.pptx$", "", value, flags=re.I).strip(" .-")
    suffix = "-native.pptx"
    remaining = 200 - len(suffix.encode("utf-8"))
    characters: list[str] = []
    for character in value:
        size = len(character.encode("utf-8"))
        if size > remaining:
            break
        characters.append(character)
        remaining -= size
    return ("".join(characters).rstrip(" .-") or "Presentation") + suffix


@contextmanager
def _directory(root: Path, parts: tuple[str, ...], *, create: bool = False):
    if not root.is_absolute() or ".." in root.parts or not hasattr(os, "O_NOFOLLOW"):
        raise NativeDownloadNotFound("Native download storage is unavailable")
    fd = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(root.anchor, flags)
        for part in root.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        for part in parts:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=fd)
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    except OSError as exc:
        raise NativeDownloadNotFound("Native download storage is unavailable") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _read(fd: int, name: str, limit: int) -> tuple[bytes, os.stat_result]:
    handle = None
    try:
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
            raise NativeDownloadNotFound("Native download not found")
        with os.fdopen(handle, "rb") as file:
            handle = None
            content = file.read(limit + 1)
        if len(content) != info.st_size or len(content) > limit:
            raise NativeDownloadNotFound("Native download not found")
        return content, info
    except OSError as exc:
        raise NativeDownloadNotFound("Native download not found") from exc
    finally:
        if handle is not None:
            os.close(handle)


def _remove_created(fd: int, name: str, created: os.stat_result) -> None:
    try:
        current = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if (stat.S_ISREG(current.st_mode) and current.st_nlink == 1
            and current.st_ino == created.st_ino and current.st_dev == created.st_dev):
            os.unlink(name, dir_fd=fd)
    except OSError:
        pass


@contextmanager
def _owner_lock(fd: int):
    if fcntl is None:
        raise NativeDownloadNotFound("Safe native file delivery is unavailable on this platform")
    handle = os.open(".native-download.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise NativeDownloadNotFound("Native download storage is unavailable")
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def _write(fd: int, name: str, content: bytes) -> os.stat_result:
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    created = os.fstat(handle)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
            return os.fstat(file.fileno())
    except BaseException:
        # Roll back only the inode this attempt created, including fsync errors.
        _remove_created(fd, name, created)
        raise


def _is_pptx(content: bytes) -> bool:
    if not content.startswith(b"PK") or len(content) > MAX_DOWNLOAD_BYTES:
        return False
    try:
        with ZipFile(BytesIO(content)) as archive:
            names = set(archive.namelist())
            return {"[Content_Types].xml", "ppt/presentation.xml"} <= names and not any(
                name.startswith("/") or ".." in name.split("/") for name in names
            )
    except (BadZipFile, ValueError):
        return False


def _metadata(fd: int, owner: str, file_id: str) -> dict:
    try:
        raw, _ = _read(fd, file_id + ".json", 16384)
        data = json.loads(raw)
        created, expires = data["created_at"], data["expires_at"]
        if (data["schema"] != _SCHEMA or data["owner"] != owner or data["file_id"] != file_id
            or not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(created)
            or not isinstance(expires, (int, float)) or isinstance(expires, bool) or not math.isfinite(expires)
            or not 0 < expires - created <= DOWNLOAD_TTL_SECONDS
            or not isinstance(data["file_name"], str) or len(data["file_name"]) > 200
            or re.search(r"[\x00-\x1f\x7f/\\]", data["file_name"]) or not data["file_name"].endswith(".pptx")
            or not isinstance(data["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"])):
            raise ValueError()
        return data
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise NativeDownloadNotFound("Native download not found") from exc


def _remove_pair(fd: int, file_id: str, metadata: dict) -> None:
    # Never follow or unlink a replaced link/foreign inode during cleanup.
    try:
        info = os.stat(file_id + ".pptx", dir_fd=fd, follow_symlinks=False)
        if (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_ino == metadata["inode"] and info.st_dev == metadata["device"]):
            os.unlink(file_id + ".pptx", dir_fd=fd)
            os.unlink(file_id + ".json", dir_fd=fd)
    except (OSError, KeyError):
        pass


def _cleanup_owner(fd: int, owner: str, now: float) -> None:
    for name in os.listdir(fd):
        if not name.endswith(".json") or not _FILE_ID.fullmatch(name[:-5]):
            continue
        try:
            metadata = _metadata(fd, owner, name[:-5])
            if metadata["expires_at"] <= now:
                _remove_pair(fd, name[:-5], metadata)
        except NativeDownloadNotFound:
            continue


def create_native_download(root: Path, owner_id: uuid.UUID, content: bytes, title: str | None, *, now: float | None = None) -> dict:
    if not isinstance(owner_id, uuid.UUID) or not isinstance(content, bytes) or not _is_pptx(content):
        raise ValueError("Only generated PowerPoint files can be stored for native download")
    now = time.time() if now is None else now
    owner, file_id = str(owner_id), uuid.uuid4().hex
    with _directory(root, ("exports", "users", owner, NATIVE_DOWNLOAD_DIRECTORY), create=True) as fd:
        with _owner_lock(fd):
            _cleanup_owner(fd, owner, now)
            if sum(bool(_FILE_ID.fullmatch(name[:-5])) for name in os.listdir(fd) if name.endswith(".pptx")) >= MAX_OWNER_DOWNLOADS:
                raise ValueError("Too many temporary native downloads. Wait for earlier links to expire.")
            info = _write(fd, file_id + ".pptx", content)
            metadata = {"schema": _SCHEMA, "owner": owner, "file_id": file_id,
                        "created_at": now, "expires_at": now + DOWNLOAD_TTL_SECONDS,
                        "file_name": native_download_filename(title), "sha256": hashlib.sha256(content).hexdigest(),
                        "size": info.st_size, "inode": info.st_ino, "device": info.st_dev}
            try:
                _write(fd, file_id + ".json", json.dumps(metadata, ensure_ascii=True).encode("ascii"))
            except BaseException:
                _remove_created(fd, file_id + ".pptx", info)
                raise
    return {"url": f"/app_data/exports/users/{owner}/{NATIVE_DOWNLOAD_DIRECTORY}/{file_id}.pptx",
            "file_name": metadata["file_name"], "expires_at": metadata["expires_at"]}


def read_native_download(root: Path, owner_id: uuid.UUID, file_id: str, *, now: float | None = None) -> tuple[bytes, str]:
    if not isinstance(owner_id, uuid.UUID) or not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
        raise NativeDownloadNotFound("Native download not found")
    now = time.time() if now is None else now
    with _directory(root, ("exports", "users", str(owner_id), NATIVE_DOWNLOAD_DIRECTORY)) as fd:
        metadata = _metadata(fd, str(owner_id), file_id)
        if metadata["created_at"] > now + 1 or metadata["expires_at"] <= now:
            _remove_pair(fd, file_id, metadata)
            raise NativeDownloadNotFound("Native download not found")
        content, info = _read(fd, file_id + ".pptx", MAX_DOWNLOAD_BYTES)
        if (info.st_ino != metadata.get("inode") or info.st_dev != metadata.get("device")
            or len(content) != metadata.get("size")
            or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), metadata["sha256"])
            or not _is_pptx(content)):
            raise NativeDownloadNotFound("Native download not found")
        return content, metadata["file_name"]


def cleanup_native_downloads(root: Path, *, now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        with _directory(root, ("exports", "users")) as users_fd:
            owners = [name for name in os.listdir(users_fd) if _OWNER.fullmatch(name)]
        for owner in owners:
            try:
                with _directory(root, ("exports", "users", owner, NATIVE_DOWNLOAD_DIRECTORY)) as fd:
                    with _owner_lock(fd):
                        _cleanup_owner(fd, owner, now)
            except NativeDownloadNotFound:
                continue
    except NativeDownloadNotFound:
        pass


@asynccontextmanager
async def native_download_cleanup(root: Path):
    async def loop():
        while True:
            await asyncio.to_thread(cleanup_native_downloads, root)
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
