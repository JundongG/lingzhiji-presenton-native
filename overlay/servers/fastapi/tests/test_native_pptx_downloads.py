# Authenticated Native PPTX temporary delivery tests. SPDX-License-Identifier: Apache-2.0
"""Only synthetic sessions/files under TemporaryDirectory; no real app config/DB."""
import ast
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote
import uuid
from zipfile import ZipFile

import httpx
from fastapi import FastAPI
from api.v1.auth.context import set_current_owner_id, reset_current_owner_id
from services import native_pptx_downloads as storage
from services.native_standard_pptx import export_standard_pptx
from api.v1.ppt.endpoints import native_pptx_download as download_route

stub = ModuleType("services.database")
async def fake_dependency():
    raise AssertionError("Test must override database dependency")
stub.get_async_session = fake_dependency
previous = sys.modules.get("services.database")
sys.modules["services.database"] = stub
try:
    export_route = importlib.import_module("api.v1.ppt.endpoints.native_pptx")
finally:
    if previous is None:
        sys.modules.pop("services.database", None)
    else:
        sys.modules["services.database"] = previous

OWNER, OTHER, DECK = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
SOURCE = Path(__file__).resolve().parents[3]


class Session:
    def __init__(self):
        self.calls = 0
        self.presentation = SimpleNamespace(id=DECK, owner_id=OWNER, title='季度预算 中文 / "测试"\r\n', generation_mode="standard", version="v2-standard", n_slides=1, theme=None)
        self.slides = [SimpleNamespace(id=uuid.uuid4(), presentation=DECK, owner_id=OWNER, index=0, ui={"elements": [], "components": []})]
    async def scalar(self, statement):
        self.calls += 1
        params = statement.compile().params
        return self.presentation if params["owner_id_1"] == OWNER and params["id_1"] == DECK else None
    async def scalars(self, statement):
        self.calls += 1
        assert statement.compile().params["owner_id_1"] == OWNER
        return self.slides


class NativeDownloadHttpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="native-download-http-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.app_data = self.root / "data"
        self.app_data.mkdir()
        self.session = Session()
        self.app = FastAPI()
        self.app.include_router(export_route.NATIVE_PPTX_ROUTER, prefix="/api/v1/ppt")
        self.app.include_router(download_route.NATIVE_DOWNLOAD_ROUTER)
        self.app.mount("/app_data", download_route.NativeProtectedAppDataFiles(directory=self.app_data))
        async def session_dependency():
            yield self.session
        self.app.dependency_overrides[export_route.get_async_session] = session_dependency
        @self.app.middleware("http")
        async def synthetic_auth(request, call_next):
            # Test-only stand-in for the existing authenticated middleware context.
            owner = request.headers.get("x-test-owner")
            token = set_current_owner_id(uuid.UUID(owner) if owner else None)
            if owner:
                request.state.auth_principal = SimpleNamespace(user_id=uuid.UUID(owner), method=request.headers.get("x-test-method", "jwt"))
            try:
                return await call_next(request)
            finally:
                reset_current_owner_id(token)
        for module, name, value in (
            (export_route, "get_app_data_directory_env", str(self.app_data)),
            (download_route, "get_app_data_directory_env", str(self.app_data)),
            (export_route, "get_resource_path", str(self.root / "static")),
            (export_route, "_builtin_templates_root", self.root / "bundled"),
        ):
            p = patch.object(module, name, return_value=value)
            p.start(); self.addCleanup(p.stop)

    async def request(self, method, path, *, owner=OWNER, **kwargs):
        headers = kwargs.pop("headers", {})
        if owner is not None:
            headers["x-test-owner"] = str(owner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, headers=headers, **kwargs)

    async def create(self, *, owner=OWNER, **kwargs):
        return await self.request("POST", f"/api/v1/ppt/presentation/{DECK}/export/native-pptx", owner=owner, json={"delivery": "file"}, **kwargs)

    async def test_real_pptx_roundtrip_and_unicode_download_name(self):
        created = await self.create()
        self.assertEqual(created.status_code, 200, created.text)
        item = created.json()
        self.assertRegex(item["url"], rf"^/app_data/exports/users/{OWNER}/native-pptx/[0-9a-f]{{32}}\.pptx$")
        self.assertIn("季度预算", item["file_name"])
        response = await self.request("GET", item["url"])
        self.assertEqual(response.status_code, 200)
        self.assertIn(quote("季度预算"), response.headers["content-disposition"])
        self.assertNotIn("\r", response.headers["content-disposition"])
        self.assertIn("no-store", response.headers["cache-control"])
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertIn("ppt/slides/slide1.xml", archive.namelist())
        head = await self.request("HEAD", item["url"])
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertEqual(int(head.headers["content-length"]), len(response.content))

    async def test_anonymous_and_api_key_requests_cannot_create_or_download(self):
        self.assertEqual((await self.create(owner=None)).status_code, 401)
        self.assertEqual(self.session.calls, 0)
        self.assertEqual((await self.create(headers={"x-test-method": "api_key"})).status_code, 401)
        item = (await self.create()).json()
        self.assertEqual((await self.request("GET", item["url"], owner=None)).status_code, 401)
        self.assertEqual((await self.request("GET", item["url"], headers={"x-test-method": "api_key"})).status_code, 401)

    async def test_other_owner_and_guessed_ids_do_not_disclose_files(self):
        item = (await self.create()).json()
        self.assertEqual((await self.request("GET", item["url"], owner=OTHER)).status_code, 404)
        self.assertEqual((await self.request("GET", item["url"].replace(str(OWNER), str(OTHER)), owner=OTHER)).status_code, 404)
        self.assertEqual((await self.request("GET", item["url"].rsplit("/",1)[0] + "/" + uuid.uuid4().hex + ".pptx")).status_code, 404)

    async def test_expired_file_is_unavailable_even_if_file_cannot_be_cleaned_up(self):
        item = (await self.create()).json()
        physical = self.app_data / item["url"].removeprefix("/app_data/")
        with patch.object(storage.time, "time", return_value=item["expires_at"] + 1), patch.object(storage, "_remove_pair"):
            variants = [item["url"], item["url"].replace("/users/", "//users/"), item["url"].replace("native-pptx/", "%6eative-pptx/"), item["url"].replace("native-pptx/", "%256eative-pptx/"), item["url"].replace("/native-pptx/", "/native-pptx/../native-pptx/")]
            for path in variants:
                with self.subTest(path=path):
                    response = await self.request("GET", path)
                    self.assertEqual(response.status_code, 404)
                    self.assertNotEqual(response.content[:2], b"PK")
        self.assertTrue(physical.exists(), "Test must retain expired file to prove fallback is denied")

    async def test_metadata_traversal_encoded_ids_and_directory_access_are_denied(self):
        item = (await self.create()).json()
        url = item["url"]
        file_id = url.rsplit("/", 1)[1][:-5]
        for path in [url[:-5]+".json", url.rsplit("/",1)[0], url.rsplit("/",1)[0]+"/", url.replace(file_id, "%"+format(ord(file_id[0]),"02x")+file_id[1:]), url+"?x=1", url.replace("/native-pptx/", "/native-pptx/%2e%2e/")]:
            response = await self.request("GET", path)
            self.assertIn(response.status_code, (404, 307))
            self.assertNotEqual(response.content[:2], b"PK")

    async def test_non_native_symlink_alias_cannot_serve_retained_expired_native_file(self):
        item = (await self.create()).json()
        target = self.app_data / item["url"].removeprefix("/app_data/")
        alias = target.parent.parent / "alias.pptx"
        alias.symlink_to(target)
        with patch.object(storage.time, "time", return_value=item["expires_at"] + 1), patch.object(storage, "_remove_pair"):
            canonical = await self.request("GET", item["url"])
            response = await self.request("GET", f"/app_data/exports/users/{OWNER}/alias.pptx")
        self.assertEqual(canonical.status_code, 404)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(target.exists())

    async def test_native_static_fallback_is_denied_but_legacy_export_still_works(self):
        item = (await self.create()).json()
        # Double slash skips the exact router but must not reach the private bytes.
        response = await self.request("GET", item["url"].replace("/exports/", "/exports//"))
        self.assertEqual(response.status_code, 404)
        legacy = self.app_data / "exports" / "users" / str(OWNER) / "legacy.pptx"
        legacy.write_bytes(b"legacy fixture")
        response = await self.request("GET", f"/app_data/exports/users/{OWNER}/legacy.pptx")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"legacy fixture")


class NativeDownloadStorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="native-download-storage-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pptx = export_standard_pptx([{"elements": []}]).pptx_bytes
        self.item = storage.create_native_download(self.root, OWNER, self.pptx, "中文", now=1000)
        self.file_id = self.item["url"].rsplit("/",1)[1][:-5]
        self.folder = self.root / "exports" / "users" / str(OWNER) / "native-pptx"
        self.file = self.folder / (self.file_id+".pptx")

    def read(self):
        return storage.read_native_download(self.root, OWNER, self.file_id, now=1001)

    def test_expiry_cleanup_only_removes_generated_pair(self):
        original = self.root / "user-original.pptx"; original.write_bytes(b"keep original")
        self.read()
        storage.cleanup_native_downloads(self.root, now=1901)
        self.assertFalse(self.file.exists())
        self.assertFalse((self.folder/(self.file_id+".json")).exists())
        self.assertEqual(original.read_bytes(), b"keep original")
        with self.assertRaises(storage.NativeDownloadNotFound): self.read()

    def test_symlink_hardlink_fifo_and_replaced_regular_file_are_rejected(self):
        original = self.root / "original.pptx"; original.write_bytes(self.pptx)
        for kind in ("symlink", "hardlink", "fifo", "replacement"):
            self.file.unlink(missing_ok=True)
            if kind == "symlink": self.file.symlink_to(original)
            elif kind == "hardlink": os.link(original, self.file)
            elif kind == "fifo": os.mkfifo(self.file)
            else: self.file.write_bytes(b"not a PPTX")
            with self.subTest(kind=kind), self.assertRaises(storage.NativeDownloadNotFound): self.read()
            storage.cleanup_native_downloads(self.root, now=1901)
            self.assertEqual(original.read_bytes(), self.pptx)

    def test_root_and_owner_directory_symlinks_are_rejected(self):
        link = self.root / "linked-root"; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(storage.NativeDownloadNotFound): storage.read_native_download(link, OWNER, self.file_id, now=1001)
        another = self.root / "exports" / "users" / str(OTHER)
        another.symlink_to(self.folder.parent, target_is_directory=True)
        with self.assertRaises(storage.NativeDownloadNotFound): storage.create_native_download(self.root, OTHER, self.pptx, "test")

    def test_metadata_symlink_and_digest_tamper_are_rejected(self):
        metadata_path = self.folder / (self.file_id+".json")
        data = json.loads(metadata_path.read_text())
        data["sha256"] = "0"*64; metadata_path.write_text(json.dumps(data))
        with self.assertRaises(storage.NativeDownloadNotFound): self.read()
        target = self.root / "fake.json"; target.write_text(json.dumps(data))
        metadata_path.unlink(); metadata_path.symlink_to(target)
        with self.assertRaises(storage.NativeDownloadNotFound): self.read()

    def test_long_unicode_filename_is_bounded_by_utf8_bytes_without_splitting_codepoints(self):
        for title in ("中文预算报告" * 100, "📊季度评审" * 100, "a" * 500):
            filename = storage.native_download_filename(title)
            self.assertLessEqual(len(filename.encode("utf-8")), 200)
            self.assertEqual(filename.encode("utf-8").decode("utf-8"), filename)
            self.assertTrue(filename.endswith("-native.pptx"))
            item = storage.create_native_download(self.root, OTHER, self.pptx, title, now=1000)
            file_id = item["url"].rsplit("/", 1)[1][:-5]
            _, returned = storage.read_native_download(self.root, OTHER, file_id, now=1001)
            self.assertEqual(returned, filename)

    def test_arbitrary_bytes_are_never_stored(self):
        with self.assertRaises(ValueError): storage.create_native_download(self.root, OWNER, b"not PPTX", "x")

    def test_fsync_failures_leave_no_orphans_and_do_not_consume_quota(self):
        with patch.object(storage.os, "fsync", side_effect=OSError("synthetic fsync failure")):
            for _ in range(10):
                with self.assertRaises(storage.NativeDownloadNotFound):
                    storage.create_native_download(self.root, OTHER, self.pptx, "test")
        folder = self.root / "exports" / "users" / str(OTHER) / "native-pptx"
        self.assertEqual(list(folder.glob("*.pptx")), [])
        self.assertEqual(list(folder.glob("*.json")), [])
        storage.create_native_download(self.root, OTHER, self.pptx, "works after retry")

    def test_concurrent_exports_obey_owner_quota(self):
        def create_one(_):
            try:
                storage.create_native_download(self.root, OTHER, self.pptx, "parallel")
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=11) as pool:
            results = list(pool.map(create_one, range(11)))
        self.assertEqual(sum(results), storage.MAX_OWNER_DOWNLOADS)
        folder = self.root / "exports" / "users" / str(OTHER) / "native-pptx"
        self.assertEqual(len(list(folder.glob("*.pptx"))), storage.MAX_OWNER_DOWNLOADS)
        self.assertEqual(len(list(folder.glob("*.json"))), storage.MAX_OWNER_DOWNLOADS)

    def test_registration_nginx_and_proxy_boundaries(self):
        backend = SOURCE / "servers" / "fastapi"
        main = (backend / "api/main.py").read_text()
        self.assertLess(main.index("app.include_router(NATIVE_DOWNLOAD_ROUTER)"), main.index('app.mount("/app_data"'))
        self.assertIn('NativeProtectedAppDataFiles(directory=app_data_dir)', main)
        nginx = (SOURCE / "nginx.conf").read_text()
        block = nginx.split("location ~ ^/app_data/exports/(?:.*/)?native-pptx(?:/|$) {",1)[1].split("}",1)[0]
        self.assertIn("proxy_pass http://localhost:8000;",block)
        self.assertIn('no-store',block)
        self.assertNotIn("alias",block)
        self.assertIn('location /app_data/exports/ {\n      auth_request /_auth_check;\n      alias /app_data/exports/;',nginx)
        tree = ast.parse((backend / "services/presenton_cloud_proxy.py").read_text())
        assignments = [node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target,ast.Name) and target.id in {"CLOUD_GENERATION_PATHS","CLOUD_EDIT_PATHS","CLOUD_SMART_PATHS","CLOUD_API_PATH_PREFIXES","CLOUD_PRIVATE_ASSET_PATH_PREFIXES"} for target in node.targets)]
        function = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=="should_proxy_presenton_cloud")
        module = ast.Module(body=[*assignments,function],type_ignores=[]); ast.fix_missing_locations(module)
        ns={"is_native_download_path":storage.is_native_download_path}; exec(compile(module,"proxy-boundary","exec"),ns)
        self.assertFalse(ns["should_proxy_presenton_cloud"](self.item["url"]))
        self.assertTrue(ns["should_proxy_presenton_cloud"]("/app_data/exports/users/x/legacy.pptx"))

if __name__ == "__main__": unittest.main()
