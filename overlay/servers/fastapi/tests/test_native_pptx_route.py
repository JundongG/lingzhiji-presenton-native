# Native PPTX beta add-on route tests. SPDX-License-Identifier: Apache-2.0
"""Isolated HTTP tests: synthetic sessions, no app/config/user database or login."""
import copy
import importlib
from io import BytesIO
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
from zipfile import ZipFile

import httpx
from PIL import Image
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Importing the real database module initializes application configuration.
# The endpoint dependency is substituted only inside this isolated test module.
database_stub = ModuleType("services.database")
async def unused_session():
    raise AssertionError("Tests must override the database dependency")
database_stub.get_async_session = unused_session
previous_database = sys.modules.get("services.database")
sys.modules["services.database"] = database_stub
try:
    route = importlib.import_module("api.v1.ppt.endpoints.native_pptx")
finally:
    if previous_database is None:
        sys.modules.pop("services.database", None)
    else:
        sys.modules["services.database"] = previous_database
from api.v1.auth.context import set_current_owner_id, reset_current_owner_id
from services.native_standard_pptx import ExportWarning, StandardPptxExport

OWNER, OTHER, PRESENTATION = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

class Session:
    def __init__(self, *, owner=OWNER, mode="standard", version="v2-standard", ui=None, n_slides=1):
        self.presentation = SimpleNamespace(id=PRESENTATION, owner_id=owner, title='A title\r\nwith "quotes"',
            generation_mode=mode, version=version, n_slides=n_slides, theme=None)
        self.slides = [SimpleNamespace(id=uuid.uuid4(), presentation=PRESENTATION, owner_id=owner,
            index=0, ui=ui if ui is not None else {"background": "#FFFFFF", "elements": [], "components": []})]
        self.queries = []

    async def scalar(self, query):
        params = query.compile().params
        self.queries.append(query)
        # Assert the actual endpoint predicates, not just a canned fixture reply.
        assert params["owner_id_1"] == OWNER
        return self.presentation if params["id_1"] == PRESENTATION and self.presentation.owner_id == OWNER else None

    async def scalars(self, query):
        params = query.compile().params
        self.queries.append(query)
        assert params["owner_id_1"] == OWNER
        assert params["presentation_1"] == PRESENTATION
        assert "ORDER BY slides.index, slides.id" in str(query)
        return [slide for slide in self.slides if slide.owner_id == OWNER]

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected session mutation or access: {name}")

class NativeRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Even no-image requests must not consult the process's real storage
        # configuration. Image-specific tests can override these synthetic roots.
        storage = tempfile.TemporaryDirectory(prefix="native-route-default-")
        self.addCleanup(storage.cleanup)
        static_root = Path(storage.name) / "static"
        static_root.mkdir()
        app_patch = patch.object(route, "get_app_data_directory_env", return_value=None)
        static_patch = patch.object(route, "get_resource_path", return_value=str(static_root))
        builtin_patch = patch.object(route, "_builtin_templates_root", return_value=Path(storage.name) / "bundled")
        app_patch.start()
        static_patch.start()
        builtin_patch.start()
        self.addCleanup(app_patch.stop)
        self.addCleanup(static_patch.stop)
        self.addCleanup(builtin_patch.stop)

    async def call(self, session=None, owner=OWNER, body=None):
        self.session = session or Session()
        app = FastAPI()
        app.include_router(route.NATIVE_PPTX_ROUTER, prefix="/api/v1/ppt")
        app.add_middleware(CORSMiddleware, allow_origins=["http://frontend.test"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
        async def fake_session():
            yield self.session
        app.dependency_overrides[route.get_async_session] = fake_session
        token = set_current_owner_id(owner)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await client.post(f"/api/v1/ppt/presentation/{PRESENTATION}/export/native-pptx", json=body, headers={"Origin": "http://frontend.test"})
        finally:
            reset_current_owner_id(token)

    async def test_unauthenticated_fails_closed_before_database(self):
        response = await self.call(owner=None)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.session.queries, [])

    async def test_other_owner_and_unowned_decks_are_not_found(self):
        for owner in (OTHER, None):
            with self.subTest(owner=owner):
                response = await self.call(Session(owner=owner))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(len(self.session.queries), 1)

    async def test_smart_and_legacy_rejected(self):
        for kwargs in ({"mode": "smart"}, {"version": "v1-standard"}):
            response = await self.call(Session(**kwargs))
            self.assertEqual(response.status_code, 422)
            self.assertIn("Standard canvas", response.json()["detail"])

    async def test_missing_ui_rejected_with_exact_path(self):
        session = Session()
        session.slides[0].ui = None
        response = await self.call(session)
        self.assertEqual(response.status_code, 422)
        self.assertIn("slides[0].ui:", response.json()["detail"])

    async def test_incomplete_deck_and_wrong_owner_slide_rejected(self):
        response = await self.call(Session(n_slides=2))
        self.assertEqual(response.status_code, 409)
        session = Session()
        session.slides[0].owner_id = OTHER
        response = await self.call(session)
        self.assertEqual(response.status_code, 409)

    async def test_unsupported_element_returns_exact_path(self):
        session = Session(ui={"elements": [{"type": "image", "src": "https://never-fetch.invalid/a.png"}]})
        response = await self.call(session)
        self.assertEqual(response.status_code, 422)
        self.assertIn("slides[0].ui.elements[0]", response.json()["detail"])

    async def test_stored_ui_is_authoritative_and_output_is_pptx(self):
        session = Session()
        before = copy.deepcopy(vars(session.presentation)), copy.deepcopy([vars(s) for s in session.slides])
        # Request-supplied UI/title/owner cannot change the source of this export.
        response = await self.call(session, body={"ui": {"elements": [{"type": "image"}]}, "title": "Injected", "owner_id": str(OTHER)})
        self.assertEqual(response.status_code, 200, response.text[:500] if response.status_code != 200 else "")
        self.assertEqual(response.headers["content-type"], route.PPTX_CONTENT_TYPE)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("\n", response.headers["content-disposition"])
        self.assertNotIn("Injected", response.headers["content-disposition"])
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertIn("ppt/slides/slide1.xml", archive.namelist())
        self.assertEqual(before, (vars(session.presentation), [vars(s) for s in session.slides]))

    async def test_owned_png_is_embedded_from_temporary_authorized_storage(self):
        with tempfile.TemporaryDirectory(prefix="native-route-image-") as folder:
            root = Path(folder)
            app_data = root / "app"
            ref = f"/app_data/images/users/{OWNER}/example.png"
            file = app_data / "images" / "users" / str(OWNER) / "example.png"
            file.parent.mkdir(parents=True)
            Image.new("RGB", (20, 12), "#77aa44").save(file, format="PNG")
            original_bytes = file.read_bytes()
            ui = {"elements": [{"type": "image", "data": ref, "position": {"x": 10, "y": 20}, "size": {"width": 200, "height": 120}, "fit": "contain"}]}
            session = Session(ui=ui)
            before = copy.deepcopy(ui)
            with patch.object(route, "get_app_data_directory_env", return_value=str(app_data)), patch.object(route, "get_resource_path", return_value=str(root / "static")):
                response = await self.call(session)
            self.assertEqual(response.status_code, 200, response.text[:500] if response.status_code != 200 else "")
            with ZipFile(BytesIO(response.content)) as archive:
                pictures = [name for name in archive.namelist() if name.startswith("ppt/media/")]
                self.assertEqual(len(pictures), 1)
                with Image.open(BytesIO(archive.read(pictures[0]))) as decoded:
                    self.assertEqual(decoded.size, (20, 12))
                self.assertIn(b"<p:pic>", archive.read("ppt/slides/slide1.xml"))
            self.assertEqual(ui, before)
            self.assertEqual(file.read_bytes(), original_bytes)

    async def test_external_or_other_owner_image_is_rejected_with_exact_data_path(self):
        for ref in ("https://never-fetch.invalid/picture.png", f"/app_data/images/users/{OTHER}/picture.png"):
            response = await self.call(Session(ui={"elements": [{"type": "image", "data": ref}]}))
            self.assertEqual(response.status_code, 422)
            self.assertIn("slides[0].ui.elements[0].data:", response.json()["detail"])

    async def test_deck_ownership_checked_before_image_resolution(self):
        with patch("services.native_pptx_assets.resolve_native_image_assets", side_effect=AssertionError("No asset resolution before ownership")) as resolver:
            response = await self.call(Session(owner=OTHER, ui={"elements": [{"type": "image", "data": "/static/example.png"}]}))
        self.assertEqual(response.status_code, 404)
        resolver.assert_not_called()

    async def test_cross_origin_warning_headers_are_exposed(self):
        response = await self.call()
        self.assertEqual(response.headers["access-control-allow-origin"], "http://frontend.test")
        self.assertIn("X-Native-Pptx-Warnings", response.headers["access-control-expose-headers"])
        self.assertIn("X-Native-Pptx-Warnings-Truncated", response.headers["access-control-expose-headers"])

    async def test_large_warning_list_reports_omissions_and_stays_bounded(self):
        warnings = tuple(ExportWarning("style", f"slides[{i}].ui", "Long warning " * 100) for i in range(30))
        with patch("services.native_standard_pptx.export_standard_pptx", return_value=StandardPptxExport(b"test", warnings)):
            response = await self.call()
        self.assertEqual(response.headers["x-native-pptx-warning-count"], "30")
        self.assertGreater(int(response.headers["x-native-pptx-warnings-truncated"]), 0)
        self.assertLessEqual(len(response.headers["x-native-pptx-warnings"]), 4096)

    async def test_structured_warnings_are_serializable(self):
        result = StandardPptxExport(b"test", (ExportWarning("style", "slides[0].ui", "Example warning"),))
        with patch("services.native_standard_pptx.export_standard_pptx", return_value=result) as exporter:
            response = await self.call()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Example warning", response.headers["x-native-pptx-warnings"])
        self.assertEqual(exporter.call_args.kwargs["unsupported"], "error")

if __name__ == "__main__":
    unittest.main()
