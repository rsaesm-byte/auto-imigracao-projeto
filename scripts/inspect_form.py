"""
inspect_form.py — List every AcroForm field in a USCIS PDF and emit a mapping skeleton.

Usage:
    python scripts/inspect_form.py data/forms/i-130.pdf
    python scripts/inspect_form.py data/forms/i-130.pdf --out data/mappings/i-130.json
"""

import sys
import json
import argparse
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    print("ERROR: pypdf not installed. Run: pip install pypdf", file=sys.stderr)
    sys.exit(1)


FIELD_TYPE_NAMES = {
    "/Tx": "text",
    "/Btn": "button",   # checkbox or radio
    "/Ch": "choice",    # dropdown / listbox
    "/Sig": "signature",
}


def get_field_type(field) -> str:
    ft = field.field_type
    if ft is None:
        return "unknown"
    name = FIELD_TYPE_NAMES.get(str(ft), str(ft))
    # Distinguish checkbox vs radio for /Btn
    if name == "button":
        flags = field.flags or 0
        if flags & (1 << 15):   # bit 16 = Radio
            return "radio"
        return "checkbox"
    return name


def get_options(field) -> list:
    """Return options for choice/radio fields."""
    opts = []
    try:
        if hasattr(field, "options") and field.options:
            opts = [str(o) for o in field.options]
    except Exception:
        pass
    return opts


def inspect_pdf(pdf_path: Path) -> list[dict]:
    reader = PdfReader(str(pdf_path))
    fields = reader.get_fields()
    if not fields:
        print("WARNING: No AcroForm fields found in this PDF.", file=sys.stderr)
        return []

    rows = []
    for name, field in fields.items():
        ftype = get_field_type(field)
        entry = {
            "pdf_field": name,
            "type": ftype,
            "question_id": "",          # fill in during mapping step
            "notes": "",
        }
        opts = get_options(field)
        if opts:
            entry["options"] = opts
        rows.append(entry)

    return rows


def emit_skeleton(rows: list[dict], form_name: str) -> dict:
    return {
        "form": form_name,
        "description": f"Field mapping skeleton for {form_name} — edit question_id for each field.",
        "fields": rows,
    }


def main():
    parser = argparse.ArgumentParser(description="Inspect AcroForm fields in a USCIS PDF.")
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("--out", help="Output JSON path (default: stdout)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: File not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    form_name = pdf_path.stem.upper()   # e.g. "I-130"
    rows = inspect_pdf(pdf_path)
    skeleton = emit_skeleton(rows, form_name)

    output = json.dumps(skeleton, indent=2, ensure_ascii=False)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Mapping skeleton written to {out_path}  ({len(rows)} fields)")
    else:
        print(output)


if __name__ == "__main__":
    main()
