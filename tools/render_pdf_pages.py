from pathlib import Path
import sys

import pypdfium2 as pdfium


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: render_pdf_pages.py input.pdf output_dir", file=sys.stderr)
        return 2
    pdf_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    for i, page in enumerate(pdf, start=1):
        bitmap = page.render(scale=2.0)
        image = bitmap.to_pil()
        image.save(out_dir / f"page-{i}.png")
    print(f"rendered_pages={len(pdf)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

