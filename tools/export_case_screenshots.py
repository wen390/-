from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
TARGET_WIDTH = 2200
PANEL_HEIGHT = 820


def trim_whitespace(img: Image.Image, margin: int = 28) -> Image.Image:
    bg = Image.new(img.mode, img.size, "white")
    diff = Image.eval(ImageChops.difference(img, bg), lambda px: 255 if px > 12 else 0)
    bbox = diff.getbbox()
    if not bbox:
        return img
    left = max(0, bbox[0] - margin)
    top = max(0, bbox[1] - margin)
    right = min(img.width, bbox[2] + margin)
    bottom = min(img.height, bbox[3] + margin)
    return img.crop((left, top, right, bottom))


def render_pdf_first_page(pdf_path: Path, out_path: Path, target_w: int = TARGET_WIDTH) -> None:
    doc = pdfium.PdfDocument(str(pdf_path))
    page = doc[0]
    width, height = page.get_size()
    bitmap = page.render(scale=target_w / width)
    img = bitmap.to_pil().convert("RGB")
    img.save(out_path, quality=96)


def render_simple_svg(svg_path: Path, out_path: Path, target_w: int = TARGET_WIDTH) -> None:
    root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
    if "viewBox" in root.attrib:
        _, _, vw, vh = [float(x) for x in root.attrib["viewBox"].split()]
    else:
        vw = float(root.attrib.get("width", "760").replace("px", ""))
        vh = float(root.attrib.get("height", "440").replace("px", ""))
    scale = target_w / vw
    img = Image.new("RGB", (int(vw * scale), int(vh * scale)), "white")
    draw = ImageDraw.Draw(img)
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "rect":
            x = float(elem.attrib.get("x", 0)) * scale
            y = float(elem.attrib.get("y", 0)) * scale
            w = float(elem.attrib.get("width", 0)) * scale
            h = float(elem.attrib.get("height", 0)) * scale
            fill = elem.attrib.get("fill", "#fff")
            outline = elem.attrib.get("stroke")
            sw = max(1, int(float(elem.attrib.get("stroke-width", 0.1)) * scale))
            draw.rectangle((x, y, x + w, y + h), fill=fill, outline=outline, width=sw)
        elif tag == "polyline":
            pts = []
            for raw in elem.attrib.get("points", "").split():
                if "," not in raw:
                    continue
                a, b = raw.split(",", 1)
                pts.append((float(a) * scale, float(b) * scale))
            if len(pts) > 1:
                sw = max(2, int(float(elem.attrib.get("stroke-width", 0.22)) * scale))
                draw.line(pts, fill=elem.attrib.get("stroke", "#3578b8"), width=sw, joint="curve")
        elif tag == "circle":
            cx = float(elem.attrib.get("cx", 0)) * scale
            cy = float(elem.attrib.get("cy", 0)) * scale
            r = float(elem.attrib.get("r", 0)) * scale
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=elem.attrib.get("fill", "#000"))
    img.save(out_path, quality=96)


def upscale_png(src: Path, out: Path, target_w: int = TARGET_WIDTH) -> None:
    img = Image.open(src).convert("RGB")
    if img.width < target_w:
        h = int(img.height * target_w / img.width)
        img = img.resize((target_w, h), Image.Resampling.LANCZOS)
    img.save(out, quality=96)


def fit_panel(path: Path, height: int = PANEL_HEIGHT) -> Image.Image:
    img = Image.open(path).convert("RGB")
    scale = height / img.height
    return img.resize((max(1, int(img.width * scale)), height), Image.Resampling.LANCZOS)


def label_font(size: int = 34):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def combine_panels(panels: list[tuple[str, Path]], out: Path) -> None:
    font = label_font()
    label_h = 64
    gap = 36
    pad = 44
    rendered = [(label, fit_panel(path)) for label, path in panels if path.exists()]
    width = sum(img.width for _, img in rendered) + gap * (len(rendered) - 1) + pad * 2
    height = PANEL_HEIGHT + label_h + pad * 2
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    x = pad
    for label, img in rendered:
        draw.text((x, pad), label, fill="#1f2933", font=font)
        sheet.paste(img, (x, pad + label_h))
        x += img.width + gap
    sheet.save(out, quality=96)


def export_case(case_dir: Path, output_root: Path, original_prefix: str, include_overlay: bool) -> None:
    out_dir = output_root / case_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    original_pdf = case_dir / f"{original_prefix}.pdf"
    original_png = out_dir / "01_original_pcb.png"
    if original_pdf.exists():
        render_pdf_first_page(original_pdf, original_png)
    elif (case_dir / f"{original_prefix}.png").exists():
        upscale_png(case_dir / f"{original_prefix}.png", original_png)

    baseline = out_dir / "02_baseline_rule.png"
    if (case_dir / "layout_baseline_rule.svg").exists():
        render_simple_svg(case_dir / "layout_baseline_rule.svg", baseline)

    algorithm = out_dir / "03_algorithm_pso_congestion_reroute_astar.png"
    if (case_dir / "layout_pso_congestion_reroute_astar.svg").exists():
        render_simple_svg(case_dir / "layout_pso_congestion_reroute_astar.svg", algorithm)

    panels = [("原始PCB", original_png), ("规则基线", baseline), ("设计算法", algorithm)]
    if include_overlay and (case_dir / "eda_parse_overlay.png").exists():
        overlay = out_dir / "02_parse_overlay.png"
        upscale_png(case_dir / "eda_parse_overlay.png", overlay)
        panels = [("原始PCB", original_png), ("解析覆盖", overlay), ("规则基线", baseline), ("设计算法", algorithm)]

    combine_panels(panels, out_dir / "00_case_comparison_highres.png")


def export_group(group: str, original_prefix: str, include_overlay: bool) -> None:
    root = ROOT / "results" / group
    out = root / "separate_screenshots"
    out.mkdir(parents=True, exist_ok=True)
    case_dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / f"{original_prefix}.pdf").exists())
    for case_dir in case_dirs:
        export_case(case_dir, out, original_prefix, include_overlay)
    write_index(out, group, case_dirs)


def write_index(out: Path, group: str, case_dirs: list[Path]) -> None:
    lines = [f"# {group} 独立高清截图", ""]
    for case_dir in case_dirs:
        rel = case_dir.name
        lines.extend(
            [
                f"## {rel}",
                f"- 原始PCB：`{rel}/01_original_pcb.png`",
                f"- 规则基线：`{rel}/02_baseline_rule.png`",
                f"- 设计算法：`{rel}/03_algorithm_pso_congestion_reroute_astar.png`",
                f"- 高清对比：`{rel}/00_case_comparison_highres.png`",
            ]
        )
        if (out / rel / "02_parse_overlay.png").exists():
            lines.insert(-2, f"- 解析覆盖：`{rel}/02_parse_overlay.png`")
        lines.append("")
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    export_group("eda_cases", "original_eda_pcb", include_overlay=True)
    export_group("kicad_cases", "original_kicad_pcb", include_overlay=False)
    print("exported separate high-resolution screenshots")


if __name__ == "__main__":
    main()
