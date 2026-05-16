from __future__ import annotations

import csv
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "data" / "eda_cases"
RESULT_DIR = ROOT / "results" / "eda_cases"
DEFAULT_KICAD_CLI = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")


SOURCES = [
    {
        "id": "pcie_test_dual_ww37",
        "repo": "mengstr/PCIeTestPCB",
        "url": "https://github.com/mengstr/PCIeTestPCB",
        "license": "CC0-1.0",
        "pcb": ROOT / "data/kicad_public/PCIeTestPCB/PCIeTest.kicad_pcb",
    },
    {
        "id": "pi5_pcie_breakout",
        "repo": "m1geo/Pi5_PCIe",
        "url": "https://github.com/m1geo/Pi5_PCIe",
        "license": "MIT",
        "pcb": ROOT / "data/kicad_public/Pi5_PCIe/Pi5_PCIe.kicad_pcb",
    },
    {
        "id": "pi5_m2_hat",
        "repo": "m1geo/Pi5_PCIe",
        "url": "https://github.com/m1geo/Pi5_PCIe",
        "license": "MIT",
        "pcb": ROOT / "data/kicad_public/Pi5_PCIe/Pi5_M2_Hat.kicad_pcb",
    },
    {
        "id": "pcie_aux_signal_breakout",
        "repo": "Supercookiegaming/PCIe-Aux-Signal-Breakout",
        "url": "https://github.com/Supercookiegaming/PCIe-Aux-Signal-Breakout",
        "license": "not specified",
        "pcb": ROOT / "data/kicad_public/PCIe-Aux-Signal-Breakout/KiCad/PCIe-Aux-Signal-Breakout/PCIe-Aux-Signal-Breakout.kicad_pcb",
        "gerber_dir": ROOT / "data/kicad_public/PCIe-Aux-Signal-Breakout/Gerber",
    },
    {
        "id": "mini_pcie_reference",
        "repo": "mithro/kicad-mini-pci-express",
        "url": "https://github.com/mithro/kicad-mini-pci-express",
        "license": "Apache-2.0",
        "pcb": ROOT / "data/kicad_public/kicad-mini-pci-express/mpcie.kicad_pcb",
    },
    {
        "id": "coral_dual_m2_adapter",
        "repo": "serg987/coral-dual-m2-adapter-pcb",
        "url": "https://github.com/serg987/coral-dual-m2-adapter-pcb",
        "license": "GPL-3.0",
        "pcb": ROOT / "data/kicad_public/coral-dual-m2-adapter-pcb/kicad_project/m2_coral_dual_adapter/m2_coral_dual_adapter.kicad_pcb",
    },
    {
        "id": "usb3_ngff_carrier",
        "repo": "themainframe/5g-m2-usb3-interface-pcb",
        "url": "https://github.com/themainframe/5g-m2-usb3-interface-pcb",
        "license": "MIT",
        "pcb": ROOT / "data/kicad_public/5g-m2-usb3-interface-pcb/usb3-ngff-carrier.kicad_pcb",
        "gerber_dir": ROOT / "data/kicad_public/5g-m2-usb3-interface-pcb/gerbers/iss-b",
    },
]


@dataclass
class Pad:
    name: str
    pad_type: str
    x: float
    y: float


@dataclass
class Footprint:
    name: str
    x: float
    y: float
    rot: float
    pads: list[Pad]


def find_blocks(text: str, head: str) -> list[str]:
    out = []
    i = 0
    needle = f"({head}"
    while True:
        start = text.find(needle, i)
        if start < 0:
            break
        depth = 0
        in_str = False
        esc = False
        for j in range(start, len(text)):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    out.append(text[start : j + 1])
                    i = j + 1
                    break
        else:
            break
    return out


def parse_at(block: str) -> tuple[float, float, float]:
    m = re.search(r"\(at\s+([-0-9.]+)\s+([-0-9.]+)(?:\s+([-0-9.]+))?", block)
    if not m:
        return 0.0, 0.0, 0.0
    return float(m.group(1)), float(m.group(2)), float(m.group(3) or 0.0)


def rotate(dx: float, dy: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return dx * math.cos(rad) - dy * math.sin(rad), dx * math.sin(rad) + dy * math.cos(rad)


def parse_footprints(text: str) -> list[Footprint]:
    footprints: list[Footprint] = []
    blocks = find_blocks(text, "footprint") + find_blocks(text, "module")
    for block in blocks:
        m = re.match(r'\((?:footprint|module)\s+"?([^"\s)]+)"?', block)
        if not m:
            continue
        name = m.group(1)
        fx, fy, rot = parse_at(block)
        pads: list[Pad] = []
        for pad_block in find_blocks(block, "pad"):
            pm = re.match(r'\(pad\s+(?:"([^"]*)"|([^\s)]+))\s+([^\s)]+)', pad_block)
            if not pm:
                continue
            pname = pm.group(1) if pm.group(1) is not None else pm.group(2)
            ptype = pm.group(3)
            px, py, _ = parse_at(pad_block)
            rx, ry = rotate(px, py, rot)
            pads.append(Pad(pname or "", ptype, fx + rx, fy + ry))
        footprints.append(Footprint(name, fx, fy, rot, pads))
    return footprints


def board_bbox_from_kicad(text: str, footprints: list[Footprint]) -> tuple[float, float, float, float]:
    pts = []
    for m in re.finditer(r'\((?:gr_line|fp_line)\s+.*?\(start\s+([-0-9.]+)\s+([-0-9.]+)\).*?\(end\s+([-0-9.]+)\s+([-0-9.]+)\).*?\(layer\s+"?Edge\.Cuts"?\)', text, re.S):
        pts.append((float(m.group(1)), float(m.group(2))))
        pts.append((float(m.group(3)), float(m.group(4))))
    if not pts:
        for fp in footprints:
            pts.extend((p.x, p.y) for p in fp.pads)
    xs = [p[0] for p in pts] or [0.0, 100.0]
    ys = [p[1] for p in pts] or [0.0, 50.0]
    return min(xs), min(ys), max(xs), max(ys)


def footprint_score(fp: Footprint) -> tuple[int, int, int, float]:
    key = fp.name.lower()
    keyword = any(k in key for k in ["pcie", "pci", "express", "m.2", "m2", "ngff", "edge", "pad", "ww", "mpcie"])
    electrical = [p for p in fp.pads if p.name and p.pad_type not in {"np_thru_hole"}]
    connect = [p for p in fp.pads if p.pad_type == "connect"]
    xs = [p.x for p in electrical]
    span = max(xs) - min(xs) if len(xs) > 1 else 0.0
    return (1 if keyword else 0, len(connect), len({p.name for p in electrical}), span)


def select_connector(footprints: list[Footprint]) -> tuple[Footprint, list[Pad]]:
    candidates = [fp for fp in footprints if len({p.name for p in fp.pads if p.name}) >= 20]
    if not candidates:
        raise RuntimeError("no connector-like footprint found")
    fp = max(candidates, key=footprint_score)
    pads = [p for p in fp.pads if p.name and p.pad_type not in {"np_thru_hole"}]
    by_name: dict[str, Pad] = {}
    for p in pads:
        if p.name not in by_name or p.y > by_name[p.name].y:
            by_name[p.name] = p
    selected = sorted(by_name.values(), key=lambda p: (p.x, p.y, p.name))
    return fp, selected


def median_pitch(pads: list[Pad]) -> float:
    xs = sorted({round(p.x, 3) for p in pads})
    diffs = [b - a for a, b in zip(xs, xs[1:]) if b - a > 0.05]
    if not diffs:
        return 1.0
    diffs.sort()
    return max(0.4, min(2.54, diffs[len(diffs) // 2]))


def map_pins_to_tailboard(pads: list[Pad], width: float) -> str:
    xs = [p.x for p in pads]
    min_x, max_x = min(xs), max(xs)
    span = max(0.001, max_x - min_x)
    margin = 4.0
    mapped = []
    for i, p in enumerate(sorted(pads, key=lambda pad: (pad.x, pad.y, pad.name)), 1):
        x = margin + (p.x - min_x) / span * max(1.0, width - 2 * margin)
        mapped.append(f"{i}:{x:.3f}:0.000")
    return ";".join(mapped)


def kicad_obstacles(footprints: list[Footprint], selected: Footprint, bbox: tuple[float, float, float, float], width: float, height: float) -> str:
    bx1, by1, bx2, by2 = bbox
    bw = max(0.001, bx2 - bx1)
    bh = max(0.001, by2 - by1)
    rects = []
    for fp in footprints:
        if fp is selected or not fp.pads:
            continue
        names = {p.name for p in fp.pads if p.name}
        if len(names) >= 20:
            continue
        x = (fp.x - bx1) / bw * width
        y = 10.0 + (fp.y - by1) / bh * max(1.0, height - 14.0)
        if 4.0 <= x <= width - 4.0 and 8.0 <= y <= height - 4.0:
            rects.append((x - 2.8, y - 1.8, x + 2.8, y + 1.8))
        if len(rects) >= 4:
            break
    if not rects:
        return "none"
    return ";".join(f"{max(1,r[0]):.1f}:{max(5,r[1]):.1f}:{min(width-1,r[2]):.1f}:{min(height-1,r[3]):.1f}" for r in rects)


def parse_gerber_bounds(path: Path) -> tuple[float, float, float, float] | None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    scale = 1e-6
    if "%MOIN" in text:
        scale *= 25.4
    pts = []
    for m in re.finditer(r"X(-?\d+)Y(-?\d+)", text):
        pts.append((int(m.group(1)) * scale, int(m.group(2)) * scale))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def parse_drill_count(path: Path) -> int:
    count = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if re.match(r"^X[-0-9.]+Y[-0-9.]+", line.strip()):
            count += 1
    return count


def gerber_metadata(gerber_dir: Path | None) -> dict:
    if not gerber_dir or not gerber_dir.exists():
        return {"gerber_files": 0, "drill_files": 0, "drill_hits": 0, "gerber_bbox": ""}
    gerbers = sorted(gerber_dir.glob("*.gbr"))
    drills = sorted(gerber_dir.glob("*.drl"))
    bounds = []
    for g in gerbers:
        if "Edge" in g.name or "Profile" in g.name or "Cut" in g.name:
            bbox = parse_gerber_bounds(g)
            if bbox:
                bounds.append(bbox)
    drill_hits = sum(parse_drill_count(d) for d in drills)
    bbox_str = ""
    if bounds:
        bbox = bounds[0]
        bbox_str = f"{bbox[0]:.2f}:{bbox[1]:.2f}:{bbox[2]:.2f}:{bbox[3]:.2f}"
    return {"gerber_files": len(gerbers), "drill_files": len(drills), "drill_hits": drill_hits, "gerber_bbox": bbox_str}


def scenario_from_eda(src: dict, index: int) -> dict:
    text = src["pcb"].read_text(encoding="utf-8", errors="ignore")
    footprints = parse_footprints(text)
    selected_fp, pads = select_connector(footprints)
    bbox = board_bbox_from_kicad(text, footprints)
    pitch = median_pitch(pads)
    span = max(p.x for p in pads) - min(p.x for p in pads) if len(pads) > 1 else pitch * len(pads)
    board_w = max(1.0, bbox[2] - bbox[0])
    width = max(48.0, min(150.0, max(span + 18.0, board_w * 0.78)))
    height = max(34.0, min(64.0, 24.0 + 0.16 * len(pads)))
    pin_positions = map_pins_to_tailboard(pads, width)
    obstacles = kicad_obstacles(footprints, selected_fp, bbox, width, height)
    gerber = gerber_metadata(src.get("gerber_dir"))
    return {
        "case_file": f"eda_case_{index:02d}_{src['id']}.csv",
        "name": f"eda_{src['id']}",
        "repo": src["repo"],
        "url": src["url"],
        "license": src["license"],
        "pcb": str(src["pcb"].relative_to(ROOT)),
        "gerber_dir": str(src["gerber_dir"].relative_to(ROOT)) if src.get("gerber_dir") else "",
        "footprint": selected_fp.name,
        "footprints": len(footprints),
        "pins": len(pads),
        "width_mm": round(width, 2),
        "tail_height_mm": round(height, 2),
        "pin_pitch_mm": round(pitch, 3),
        "pin_positions": pin_positions,
        "grid_mm": 1.0,
        "min_testpoint_spacing_mm": 1.8 if pitch < 1.0 else 2.0,
        "line_spacing_mm": 0.5,
        "max_iterations": 100,
        "obstacles": obstacles,
        **gerber,
    }


def write_case(case: dict) -> Path:
    CASE_DIR.mkdir(parents=True, exist_ok=True)
    path = CASE_DIR / case["case_file"]
    lines = [
        f"# source_repo,{case['repo']}",
        f"# source_url,{case['url']}",
        f"# source_pcb,{case['pcb']}",
        f"# gerber_dir,{case['gerber_dir']}",
        f"# selected_footprint,{case['footprint']}",
        f"name,{case['name']}",
        f"pins,{case['pins']}",
        f"width_mm,{case['width_mm']}",
        f"tail_height_mm,{case['tail_height_mm']}",
        f"pin_pitch_mm,{case['pin_pitch_mm']}",
        f"pin_positions,{case['pin_positions']}",
        f"grid_mm,{case['grid_mm']}",
        f"min_testpoint_spacing_mm,{case['min_testpoint_spacing_mm']}",
        f"line_spacing_mm,{case['line_spacing_mm']}",
        f"max_iterations,{case['max_iterations']}",
        f"obstacles,{case['obstacles']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def find_kicad_cli() -> Path | None:
    candidates = []
    if os.environ.get("KICAD_CLI"):
        candidates.append(Path(os.environ["KICAD_CLI"]))
    found = shutil.which("kicad-cli")
    if found:
        candidates.append(Path(found))
    candidates.append(DEFAULT_KICAD_CLI)
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return None


def kicad_version(kicad_cli: Path | None) -> str:
    if not kicad_cli:
        return "unavailable"
    return subprocess.run([str(kicad_cli), "version"], text=True, capture_output=True, check=True).stdout.strip()


def trim_whitespace(image: Image.Image, threshold: int = 246, padding: int = 16) -> Image.Image:
    rgb = image.convert("RGB")
    pix = rgb.load()
    w, h = rgb.size
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            r, g, b = pix[x, y]
            if min(r, g, b) < threshold:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
                found = True
    if not found:
        return rgb
    return rgb.crop((max(0, min_x - padding), max(0, min_y - padding), min(w, max_x + padding), min(h, max_y + padding)))


def render_pdf_first_page(pdf_path: Path, out_path: Path, target_w: int = 760) -> None:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    page = pdf[0]
    width, _ = page.get_size()
    image = page.render(scale=target_w / width).to_pil().convert("RGB")
    trim_whitespace(image).save(out_path)


def export_kicad(case: dict, out_dir: Path, kicad_cli: Path | None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not kicad_cli:
        return {"kicad_export_status": "unavailable", "original_pcb_png": ""}
    pcb = ROOT / case["pcb"]
    svg = out_dir / "original_eda_pcb.svg"
    pdf = out_dir / "original_eda_pcb.pdf"
    png = out_dir / "original_eda_pcb.png"
    layers = "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
    try:
        subprocess.run([str(kicad_cli), "pcb", "export", "svg", "--mode-single", "--layers", layers, "--page-size-mode", "2", "--exclude-drawing-sheet", "--output", str(svg), str(pcb)], check=True)
        subprocess.run([str(kicad_cli), "pcb", "export", "pdf", "--mode-single", "--layers", layers, "--exclude-refdes", "--exclude-value", "--output", str(pdf), str(pcb)], check=True)
        render_pdf_first_page(pdf, png)
        return {"kicad_export_status": "kicad_cli", "original_pcb_png": str(png.relative_to(ROOT))}
    except subprocess.CalledProcessError:
        img = Image.new("RGB", (760, 360), "white")
        ImageDraw.Draw(img).text((20, 20), f"KiCad export failed for {case['name']}; parsed text fallback used.", fill=(40, 40, 40))
        img.save(png)
        return {"kicad_export_status": "text_parse_only", "original_pcb_png": str(png.relative_to(ROOT))}


def render_simple_svg(svg_path: Path, out_path: Path, target_w: int = 760) -> None:
    root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
    view = [float(x) for x in root.attrib["viewBox"].split()]
    _, _, vw, vh = view
    scale = target_w / vw
    img = Image.new("RGB", (int(vw * scale), int(vh * scale)), "white")
    draw = ImageDraw.Draw(img)
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "rect":
            x, y = float(elem.attrib.get("x", 0)) * scale, float(elem.attrib.get("y", 0)) * scale
            w, h = float(elem.attrib.get("width", 0)) * scale, float(elem.attrib.get("height", 0)) * scale
            draw.rectangle((x, y, x + w, y + h), fill=elem.attrib.get("fill", "#fff"), outline=elem.attrib.get("stroke"))
        elif tag == "polyline":
            pts = []
            for raw in elem.attrib.get("points", "").split():
                if "," in raw:
                    a, b = raw.split(",", 1)
                    pts.append((float(a) * scale, float(b) * scale))
            if len(pts) > 1:
                draw.line(pts, fill=elem.attrib.get("stroke", "#3578b8"), width=max(1, int(scale * 0.7)))
        elif tag == "circle":
            cx, cy, r = float(elem.attrib.get("cx", 0)) * scale, float(elem.attrib.get("cy", 0)) * scale, float(elem.attrib.get("r", 0)) * scale
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=elem.attrib.get("fill", "#000"))
    trim_whitespace(img).save(out_path)


def draw_parse_overlay(case: dict, out_dir: Path) -> Path:
    w, h = 760, 360
    img = Image.new("RGB", (w, h), "#fbfbf7")
    draw = ImageDraw.Draw(img)
    scale_x = (w - 80) / case["width_mm"]
    scale_y = (h - 80) / case["tail_height_mm"]
    draw.rectangle((40, 40, w - 40, h - 40), outline="#333", width=2)
    for raw in case["pin_positions"].split(";"):
        _, xs, ys = raw.split(":")
        x = 40 + float(xs) * scale_x
        y = 40 + float(ys) * scale_y
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="#d33f49")
    for raw in case["obstacles"].split(";"):
        if not raw or raw == "none":
            continue
        x1, y1, x2, y2 = [float(v) for v in raw.split(":")]
        draw.rectangle((40 + x1 * scale_x, 40 + y1 * scale_y, 40 + x2 * scale_x, 40 + y2 * scale_y), fill="#d7dee8", outline="#6a7380")
    draw.text((42, 14), f"{case['name']} parsed connector={case['footprint']} pins={case['pins']}", fill="#222")
    draw.text((42, h - 30), f"Gerber files={case['gerber_files']} drill files={case['drill_files']} drill hits={case['drill_hits']}", fill="#444")
    out = out_dir / "eda_parse_overlay.png"
    img.save(out)
    return out


def fit_panel(image: Image.Image, size=(760, 360)) -> Image.Image:
    canvas = Image.new("RGB", size, "white")
    im = trim_whitespace(image)
    im.thumbnail((size[0] - 12, size[1] - 12))
    canvas.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
    return canvas


def comparison(case: dict, out_dir: Path) -> Path:
    base_png = out_dir / "layout_baseline_rule.png"
    final_png = out_dir / "layout_pso_congestion_reroute_astar.png"
    render_simple_svg(out_dir / "layout_baseline_rule.svg", base_png)
    render_simple_svg(out_dir / "layout_pso_congestion_reroute_astar.svg", final_png)
    overlay = ROOT / case["parse_overlay_png"]
    original = ROOT / case["original_pcb_png"] if case.get("original_pcb_png") else overlay
    panels = [Image.open(original).convert("RGB"), Image.open(overlay).convert("RGB"), Image.open(final_png).convert("RGB")]
    titles = ["original EDA/KiCad", "parsed connector/obstacles", "proposed routing"]
    panel_size = (760, 360)
    pad, title_h = 40, 56
    img = Image.new("RGB", (panel_size[0] * 3 + pad * 4, panel_size[1] + title_h + pad), "white")
    draw = ImageDraw.Draw(img)
    for i, (title, panel) in enumerate(zip(titles, panels)):
        x = pad + i * (panel_size[0] + pad)
        draw.text((x, 18), f"{case['name']}  {title}", fill="#222")
        img.paste(fit_panel(panel, panel_size), (x, title_h))
    out = out_dir / "eda_comparison_original_parse_algorithm.png"
    img.save(out)
    return out


def read_metrics(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_case(case_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ROOT / "pcb_tail_router"), "--case", str(case_path), "--out", str(out_dir)], check=True)


def contact_sheet(cases: list[dict]) -> Path:
    rows = []
    for c in cases:
        im = Image.open(ROOT / c["comparison_png"]).convert("RGB")
        im.thumbnail((1120, 230))
        rows.append((c["name"], im.copy()))
    sheet = Image.new("RGB", (1180, 292 * len(rows) + 24), "white")
    draw = ImageDraw.Draw(sheet)
    y = 18
    for name, im in rows:
        draw.text((24, y), name, fill="#222")
        sheet.paste(im, (24, y + 24))
        y += 292
    out = RESULT_DIR / "eda_contact_sheet.png"
    sheet.save(out)
    return out


def main() -> None:
    kicad_cli = find_kicad_cli()
    version = kicad_version(kicad_cli)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    cases = []
    for i, src in enumerate(SOURCES, 1):
        if not src["pcb"].exists():
            continue
        case = scenario_from_eda(src, i)
        case_path = write_case(case)
        out_dir = RESULT_DIR / Path(case_path).stem
        run_case(case_path, out_dir)
        case.update(export_kicad(case, out_dir, kicad_cli))
        case["parse_overlay_png"] = str(draw_parse_overlay(case, out_dir).relative_to(ROOT))
        case["comparison_png"] = str(comparison(case, out_dir).relative_to(ROOT))
        case["out_dir"] = str(out_dir.relative_to(ROOT))
        cases.append(case)

    fields = [
        "case", "repo", "license", "eda_file", "gerber_dir", "footprint", "pins", "method", "coverage_percent",
        "routability_percent", "area_ratio_percent", "total_wire_mm", "violations", "congestion_peak",
        "congested_cells", "runtime_ms", "gerber_files", "drill_files", "drill_hits", "kicad_export_status",
        "parse_overlay_png", "comparison_png",
    ]
    with (RESULT_DIR / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            for row in read_metrics(ROOT / case["out_dir"] / "metrics.csv"):
                writer.writerow({
                    "case": case["name"],
                    "repo": case["repo"],
                    "license": case["license"],
                    "eda_file": case["pcb"],
                    "gerber_dir": case["gerber_dir"],
                    "footprint": case["footprint"],
                    "pins": case["pins"],
                    "method": row["method"],
                    "coverage_percent": row["coverage_percent"],
                    "routability_percent": row["routability_percent"],
                    "area_ratio_percent": row["area_ratio_percent"],
                    "total_wire_mm": row["total_wire_mm"],
                    "violations": row["violations"],
                    "congestion_peak": row["congestion_peak"],
                    "congested_cells": row["congested_cells"],
                    "runtime_ms": row["runtime_ms"],
                    "gerber_files": case["gerber_files"],
                    "drill_files": case["drill_files"],
                    "drill_hits": case["drill_hits"],
                    "kicad_export_status": case["kicad_export_status"],
                    "parse_overlay_png": case["parse_overlay_png"],
                    "comparison_png": case["comparison_png"],
                })

    source_lines = [
        "# Public EDA case sources",
        "",
        f"KiCad CLI version: `{version}`.",
        "",
        "| Case | Repository | License | EDA file | Gerber/Excellon | Selected footprint | Pins | Gerber files | Drill hits |",
        "|---|---|---|---|---|---|---:|---:|---:|",
    ]
    for c in cases:
        source_lines.append(f"| {c['name']} | [{c['repo']}]({c['url']}) | {c['license']} | `{c['pcb']}` | `{c['gerber_dir'] or 'none'}` | `{c['footprint']}` | {c['pins']} | {c['gerber_files']} | {c['drill_hits']} |")
    (RESULT_DIR / "sources.md").write_text("\n".join(source_lines) + "\n", encoding="utf-8")

    by_case: dict[str, dict[str, dict]] = {}
    with (RESULT_DIR / "summary.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_case.setdefault(row["case"], {})[row["method"]] = row
    rows = [(v["baseline_rule"], v["pso_congestion_reroute_astar"]) for v in by_case.values()]
    report = [
        "# Real EDA File Parsing and Tail-Board Routing Experiment",
        "",
        "## Environment",
        "",
        f"- KiCad CLI: `{version}`",
        "- Python parsing: built-in text/S-expression parser, lightweight Gerber/Excellon coordinate extraction, PIL/pypdfium2 rendering.",
        "- Scope: KiCad board files plus Gerber/Excellon manufacturing files where available; ODB++/IPC-2581 are reserved for future expansion.",
        "",
        "## Parsing Evidence",
        "",
        "| Case | EDA source | Connector footprint | Pins | Gerber files | Drill files | Drill hits | Export |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for c in cases:
        report.append(f"| {c['name']} | {c['repo']} | `{c['footprint']}` | {c['pins']} | {c['gerber_files']} | {c['drill_files']} | {c['drill_hits']} | {c['kicad_export_status']} |")
    report += [
        "",
        "## Quantitative Result",
        "",
        "| Case | Baseline routability/% | Proposed routability/% | Baseline area/% | Proposed area/% | Baseline violations | Proposed violations |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in cases:
        base = by_case[c["name"]]["baseline_rule"]
        final = by_case[c["name"]]["pso_congestion_reroute_astar"]
        report.append(f"| {c['name']} | {base['routability_percent']} | {final['routability_percent']} | {base['area_ratio_percent']} | {final['area_ratio_percent']} | {base['violations']} | {final['violations']} |")
    avg_base_route = sum(float(b["routability_percent"]) for b, _ in rows) / len(rows)
    avg_final_route = sum(float(f["routability_percent"]) for _, f in rows) / len(rows)
    avg_base_area = sum(float(b["area_ratio_percent"]) for b, _ in rows) / len(rows)
    avg_final_area = sum(float(f["area_ratio_percent"]) for _, f in rows) / len(rows)
    report += [
        "",
        "## Aggregate",
        "",
        f"- Average routability: {avg_base_route:.2f}% -> {avg_final_route:.2f}%.",
        f"- Average area ratio: {avg_base_area:.2f}% -> {avg_final_area:.2f}%.",
        "",
        "![EDA contact sheet](eda_contact_sheet.png)",
    ]
    contact = contact_sheet(cases)
    (RESULT_DIR / "eda_parse_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"cases={len(cases)}")
    print(f"kicad_version={version}")
    print(f"summary={RESULT_DIR / 'summary.csv'}")
    print(f"report={RESULT_DIR / 'eda_parse_report.md'}")
    print(f"contact_sheet={contact}")


if __name__ == "__main__":
    main()
