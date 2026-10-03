# SPDX-License-Identifier: Apache-2.0
# Independent native-export add-on; no licensed export-core implementation is used.
"""Generate explicitly synthetic QA files and validate their native structures.

Run from servers/fastapi:
  python tests/native_standard_export_smoke.py --output-dir /tmp/native-standard-qa

Writes only to the directory explicitly supplied by the test operator. The
exporter itself is in-memory. This runner exercises no model, cloud service,
licensed exporter, browser, or PowerPoint UI. Output 03 is specifically a
python-pptx native-edit roundtrip, not an assertion about desktop-app behavior.
"""
import argparse
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "unit"))
from services.native_standard_pptx import export_standard_pptx
from test_native_standard_pptx import NativeStandardPptxTests, edited_native_roundtrip, fixture
from test_native_standard_images import NativeStandardImageTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(NativeStandardPptxTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(NativeStandardImageTests),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = []
    revised_bytes = None
    for revised, filename in ((False, "01-synthetic-original.pptx"), (True, "02-synthetic-revised.pptx")):
        data = fixture(revised=revised)
        export = export_standard_pptx(data["slides"], title=data["title"])
        assert not export.warnings
        (args.output_dir / filename).write_bytes(export.pptx_bytes)
        files.append(filename)
        if revised:
            revised_bytes = export.pptx_bytes
    filename = "03-synthetic-native-api-edit-roundtrip.pptx"
    (args.output_dir / filename).write_bytes(edited_native_roundtrip(revised_bytes))
    files.append(filename)
    report = {"fixture": "All names, projects, figures and dates are fictional", "tests_run": result.testsRun,
              "tests_passed": True, "powerpoint_ui_tested": False, "browser_or_model_tested": False,
              "raster_fallback_used": False, "files": files,
              "roundtrip": "03 changes a native table cell and column-chart series using python-pptx, then saves and reopens them"}
    (args.output_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
