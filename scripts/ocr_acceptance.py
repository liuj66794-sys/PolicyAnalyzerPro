from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_app_config
from importers.document_loader import DocumentImportError, DocumentLoader, PdfImportOptions


EXPECTED_TOKENS = [
    "政策推进",
    "扩大内需",
    "稳定预期",
]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run end-to-end OCR acceptance for PolicyAnalyzerPro.")
    parser.add_argument(
        "--config",
        dest="config_path",
        help="Optional path to a config JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default="tmp/ocr_acceptance",
        help="Directory for generated sample files and OCR reports.",
    )
    return parser.parse_args(argv)


def build_sample_pdf(output_dir: Path, font_path: Path) -> tuple[Path, Path]:
    from PIL import Image, ImageDraw, ImageFont

    image_path = output_dir / "scan_source.png"
    pdf_path = output_dir / "scan_only.pdf"

    image = Image.new("RGB", (1800, 1200), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 72)
    y = 120
    for line in EXPECTED_TOKENS:
        draw.text((120, y), line, fill="black", font=font)
        y += 180
    image.save(image_path)
    image.save(pdf_path, "PDF", resolution=200.0)
    image.close()
    return image_path, pdf_path


def normalize_text(text: str) -> str:
    return "".join(text.split())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = load_app_config(args.config_path)
    validation_config = config.merge({"enable_ocr_result_cache": False})

    output_dir = (PROJECT_ROOT / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    font_path = Path(validation_config.resolved_font_path)
    if not font_path.exists():
        print(f"Missing font file for OCR acceptance: {font_path}", file=sys.stderr)
        return 2

    image_path, pdf_path = build_sample_pdf(output_dir, font_path)
    loader = DocumentLoader(config=validation_config)

    try:
        extracted_text = loader.load_text_from_path(
            pdf_path,
            pdf_options=PdfImportOptions(ocr_page_spec="1", use_ocr_cache=False),
        )
    except DocumentImportError as exc:
        print(f"OCR acceptance failed: {exc}", file=sys.stderr)
        return 2

    normalized = normalize_text(extracted_text)
    matched_tokens = [token for token in EXPECTED_TOKENS if token in normalized]
    report = {
        "sample_pdf": str(pdf_path.resolve()),
        "sample_image": str(image_path.resolve()),
        "font_path": str(font_path.resolve()),
        "tesseract_cmd": validation_config.tesseract_cmd,
        "extraction_mode": loader.last_load_state.extraction_mode,
        "ocr_page_range": loader.last_load_state.ocr_page_range,
        "matched_tokens": matched_tokens,
        "expected_tokens": EXPECTED_TOKENS,
        "extracted_text": extracted_text,
    }

    text_output = output_dir / "ocr_output_utf8.txt"
    json_output = output_dir / "ocr_acceptance_report.json"
    text_output.write_text(extracted_text, encoding="utf-8")
    json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OCR extraction mode: {loader.last_load_state.extraction_mode}")
    print(f"Matched tokens: {len(matched_tokens)}/{len(EXPECTED_TOKENS)} -> {', '.join(matched_tokens)}")
    print(f"OCR text output: {text_output.resolve()}")
    print(f"OCR report JSON: {json_output.resolve()}")

    if loader.last_load_state.extraction_mode != "pdf_ocr":
        print("OCR acceptance failed: extraction mode is not pdf_ocr.", file=sys.stderr)
        return 1
    if len(matched_tokens) < 2:
        print("OCR acceptance failed: not enough expected tokens were recognized.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
