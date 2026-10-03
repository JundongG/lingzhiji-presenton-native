# Native PPTX beta secure local assets tests. SPDX-License-Identifier: Apache-2.0
"""All files are synthetic and isolated under TemporaryDirectory."""
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from PIL import Image
from services import native_pptx_assets as assets
from services.native_standard_pptx import NativeStandardExportError

OWNER, OTHER = uuid.uuid4(), uuid.uuid4()


def raster(fmt="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (12, 8), "#4477aa").save(buffer, format=fmt)
    return buffer.getvalue()


def image(ref):
    return {"type": "image", "data": ref, "position": {"x": 10, "y": 10}, "size": {"width": 100, "height": 80}}


class LocalImageAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-pptx-assets-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.static = self.root / "static"
        self.app.mkdir()
        self.static.mkdir()
        self.owned = f"/app_data/images/users/{OWNER}/test.png"
        self.write(self.app / "images" / "users" / str(OWNER) / "test.png", raster())
        self.write(self.static / "sample.jpg", raster("JPEG"))

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def resolve(self, elements, **kwargs):
        return assets.resolve_native_image_assets(
            [{"components": [], "elements": elements}], owner_id=OWNER,
            app_data_root=self.app, static_root=self.static, **kwargs)

    def assert_rejected(self, ref, message=None):
        with self.assertRaises(NativeStandardExportError) as caught:
            self.resolve([image(ref)])
        self.assertEqual(caught.exception.path, "slides[0].ui.elements[0].data")
        if message:
            self.assertIn(message, str(caught.exception))

    def test_owned_and_static_rasters_are_loaded_deduplicated(self):
        result = self.resolve([image(self.owned), image("/static/sample.jpg"), image(self.owned)])
        self.assertEqual(set(result), {self.owned, "/static/sample.jpg"})
        self.assertEqual(result[self.owned], raster())

    def test_nested_rendered_slots_only_and_original_inputs_unchanged(self):
        import copy
        ui = {"elements": [{"type": "group", "children": [{"type": "container", "child": image(self.owned)}]}],
              "components": [{"elements": [{"type": "flex", "children": [image("/static/sample.jpg")]}]}],
              "metadata": {"type": "image", "data": "file:///must-never-read.png"},
              "background_image": "https://must-never-fetch.invalid/bg.png"}
        before = copy.deepcopy(ui)
        result = assets.resolve_native_image_assets([ui], owner_id=OWNER, app_data_root=self.app, static_root=self.static)
        self.assertEqual(len(result), 2)
        self.assertEqual(ui, before)

    def test_encoded_safe_names_preserve_original_mapping_keys(self):
        result = self.resolve([image("/static/%73ample.jpg")])
        self.assertIn("/static/%73ample.jpg", result)

    def test_urls_paths_queries_and_forbidden_formats_are_rejected_before_reads(self):
        cases = [
            "https://evil.invalid/static/sample.jpg", "http://localhost/static/sample.jpg", "//evil.invalid/static/sample.jpg",
            "file:///etc/secret.png", "data:image/png;base64,AAAA", "blob:unsafe", "/etc/secret.png", "sample.jpg",
            "/static/sample.jpg?anything=1", "/static/sample.jpg#fragment", "/static/../private.png", "/static/%2e%2e/private.png",
            "/static/%252e%252e/private.png", "/static/a\\b.jpg", "/static/%00.jpg", "/static/%0a.jpg", "/static/test.svg",
            f"/app_data/images/users/{OTHER}/test.png", "/app_data/images/test.png", "/app_data/templates/shared/test.png",
            f"/app_data/exports/users/{OWNER}/test.png", "/static//sample.jpg", "/static/./sample.jpg",
        ]
        with patch.object(assets, "_read_beneath", side_effect=AssertionError("No reads for invalid references")):
            for ref in cases:
                with self.subTest(ref=ref):
                    self.assert_rejected(ref)

    def test_all_references_validate_before_first_read(self):
        with patch.object(assets, "_read_beneath", side_effect=AssertionError("No reads for mixed invalid deck")):
            with self.assertRaises(NativeStandardExportError):
                self.resolve([image(self.owned), image("https://external.invalid/test.png")])

    def test_symlink_file_directory_and_root_are_rejected(self):
        outside = self.root / "outside.png"
        self.write(outside, raster())
        (self.static / "linked.png").symlink_to(outside)
        self.assert_rejected("/static/linked.png")
        (self.static / "linked-directory").symlink_to(self.root, target_is_directory=True)
        self.assert_rejected("/static/linked-directory/outside.png")
        linked_root = self.root / "linked-root"
        linked_root.symlink_to(self.static, target_is_directory=True)
        with self.assertRaises(NativeStandardExportError):
            assets.resolve_native_image_assets([{"elements": [image("/static/sample.jpg")]}], owner_id=OWNER,
                app_data_root=self.app, static_root=linked_root)

    def test_same_owner_path_cannot_link_into_another_owners_directory(self):
        other = self.app / "images" / "users" / str(OTHER)
        self.write(other / "test.png", raster())
        link = self.app / "images" / "users" / str(OWNER) / "other"
        link.symlink_to(other, target_is_directory=True)
        self.assert_rejected(f"/app_data/images/users/{OWNER}/other/test.png")

    def test_hardlinks_and_nonregular_files_are_rejected(self):
        original = self.root / "original.png"
        self.write(original, raster())
        os.link(original, self.static / "hardlink.png")
        self.assert_rejected("/static/hardlink.png")
        os.mkfifo(self.static / "fifo.png")
        self.assert_rejected("/static/fifo.png")
        (self.static / "directory.png").mkdir()
        self.assert_rejected("/static/directory.png")

    def test_missing_and_empty_files_have_no_absolute_filesystem_disclosure(self):
        self.write(self.static / "empty.png", b"")
        for ref in ("/static/missing.png", "/static/empty.png"):
            with self.assertRaises(NativeStandardExportError) as caught:
                self.resolve([image(ref)])
            self.assertNotIn(self.temp.name, str(caught.exception))

    def test_single_total_and_count_limits(self):
        with patch.object(assets, "MAX_ASSET_BYTES", 2):
            self.assert_rejected(self.owned, "budget")
        with patch.object(assets, "MAX_TOTAL_ASSET_BYTES", len(raster()) + 1):
            with self.assertRaises(NativeStandardExportError):
                self.resolve([image(self.owned), image("/static/sample.jpg")])
        with patch.object(assets, "MAX_ASSETS", 1):
            with self.assertRaises(NativeStandardExportError):
                self.resolve([image(self.owned), image("/static/sample.jpg")])

    def test_no_authenticated_owner_and_unconfigured_app_root_rejected(self):
        with self.assertRaises(NativeStandardExportError):
            assets.resolve_native_image_assets([{"elements": []}], owner_id=None, app_data_root=self.app, static_root=self.static)
        with self.assertRaises(NativeStandardExportError):
            assets.resolve_native_image_assets([{"elements": [image(self.owned)]}], owner_id=OWNER, app_data_root=None, static_root=self.static)

    def test_empty_component_traversal_is_also_bounded(self):
        with patch.object(assets, "MAX_NODES", 1), self.assertRaises(NativeStandardExportError):
            assets.resolve_native_image_assets([{"components": [{"elements": []}, {"elements": []}]}],
                owner_id=OWNER, app_data_root=self.app, static_root=self.static)

    def test_only_pinned_bundled_references_map_to_original_source(self):
        source = self.root / "bundled"
        ref = "static/image6-d77d5bd67ea3.png"
        self.write(source / "standard" / ref, raster())
        # The mutable shared copy is deliberately different and never read.
        self.write(self.app / "templates" / "standard" / ref, b"untrusted shared copy")
        for alias in (ref, f"/app_data/templates/standard/{ref}"):
            result = self.resolve([image(alias)], builtin_templates_root=source)
            self.assertEqual(result[alias], raster())
        for unknown in ("static/not-in-manifest.png", "/app_data/templates/unknown/" + ref,
                        "/app_data/templates/standard/static/not-in-manifest.png",
                        "/app_data/templates/standard/static/%69mage6-d77d5bd67ea3.png"):
            with self.assertRaises(NativeStandardExportError):
                self.resolve([image(unknown)], builtin_templates_root=source)

    def test_pinned_bundled_source_symlink_is_rejected(self):
        source = self.root / "bundled"
        target = self.root / "outside.png"
        self.write(target, raster())
        path = source / "standard" / "static" / "image6-d77d5bd67ea3.png"
        path.parent.mkdir(parents=True)
        path.symlink_to(target)
        with self.assertRaises(NativeStandardExportError):
            self.resolve([image("/app_data/templates/standard/static/image6-d77d5bd67ea3.png")], builtin_templates_root=source)

    def test_depth_and_malformed_type_fail_closed(self):
        element = image(self.owned)
        for _ in range(35):
            element = {"type": "container", "child": element}
        with self.assertRaises(NativeStandardExportError):
            self.resolve([element])
        with self.assertRaises(NativeStandardExportError):
            self.resolve([{"type": []}])

if __name__ == "__main__":
    unittest.main()
