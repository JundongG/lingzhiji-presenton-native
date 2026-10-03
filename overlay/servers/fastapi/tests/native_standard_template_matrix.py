# SPDX-License-Identifier: Apache-2.0
# Independent native-export add-on structural test runner.
"""Check bundled template prototypes using explicitly synthetic image bytes.

This does NOT fetch actual template assets, convert SVG, generate content, or
exercise the browser/model/PowerPoint UI. The resulting coverage is a structural
compatibility check, not a claim of production template fidelity. Warnings and
failures are retained in the JSON report. It never drops an unsupported chart
or table to improve the reported pass count.

Run from servers/fastapi:
  python tests/native_standard_template_matrix.py --output-dir /tmp/template-qa
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.native_standard_pptx import NativeStandardExportError, export_standard_pptx

TEMPLATES = ("standard", "general", "civic", "editorial", "executive", "swift")


def references(value):
    if isinstance(value, dict):
        if value.get("type") == "image" and isinstance(value.get("data"), str):
            yield value["data"]
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def test_pixels():
    image = Image.new("RGB", (240, 160), "#16A6A1")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 119, 79), fill="#243B62")
    draw.rectangle((120, 80, 239, 159), fill="#E7A24C")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[3]
    pixels = test_pixels()
    report = {
        "prototype_only_not_generated_deck": True,
        "every_image_reference_uses_synthetic_png": True,
        "actual_asset_resolution_tested": False,
        "svg_conversion_tested": False,
        "browser_model_powerpoint_ui_tested": False,
        "failures_and_warnings_preserved": True,
        "templates": [],
    }
    for name in TEMPLATES:
        template = json.loads((repo / "templates" / name / "template.json").read_text(encoding="utf-8"))
        items = []
        for layout in template["layouts"]:
            refs = sorted(set(references(layout)))
            item = {"id": layout["id"], "synthetic_asset_references": refs}
            try:
                result = export_standard_pptx([layout], image_assets={ref: pixels for ref in refs})
                item.update(ok=True, warnings=[{"code": warning.code, "path": warning.path, "message": warning.message}
                                               for warning in result.warnings])
            except NativeStandardExportError as exc:
                item.update(ok=False, error=str(exc), error_code=exc.code, error_path=exc.path)
            except Exception as exc:
                # Preserve unexpected implementation failures as failures, never
                # reinterpret them as unsupported content or success.
                item.update(ok=False, error=f"{type(exc).__name__}: {exc}", error_code="unexpected_internal_error")
            items.append(item)
        summary = {"template": name, "passed": sum(item["ok"] for item in items), "total": len(items), "items": items}
        report["templates"].append(summary)
        if name == "standard" and summary["passed"] == summary["total"]:
            refs = sorted(set(references(template["layouts"])))
            result = export_standard_pptx(template["layouts"], title="Standard structural prototypes — synthetic image assets",
                                          image_assets={ref: pixels for ref in refs})
            (args.output_dir / "standard-prototypes-synthetic-assets.pptx").write_bytes(result.pptx_bytes)
    (args.output_dir / "synthetic-image.png").write_bytes(pixels)
    (args.output_dir / "template-matrix.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{key: item[key] for key in ("template", "passed", "total")} for item in report["templates"]], indent=2))


if __name__ == "__main__":
    main()
