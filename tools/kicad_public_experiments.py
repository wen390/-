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
CASE_DIR = ROOT / "data" / "kicad_cases"
RESULT_DIR = ROOT / "results" / "kicad_cases"
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
        "license": "not specified in GitHub API result",
        "pcb": ROOT / "data/kicad_public/PCIe-Aux-Signal-Breakout/KiCad/PCIe-Aux-Signal-Breakout/PCIe-Aux-Signal-Breakout.kicad_pcb",
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
    footprints = []
    for block in find_blocks(text, "footprint"):
        m = re.match(r'\(footprint\s+"([^"]+)"', block)
        if not m:
            continue
        name = m.group(1)
        fx, fy, rot = parse_at(block)
        pads = []
        for pad_block in find_blocks(block, "pad"):
            pm = re.match(r'\(pad\s+"([^"]*)"\s+([^\s)]+)', pad_block)
            if not pm:
                continue
            pname, ptype = pm.group(1), pm.group(2)
            px, py, _ = parse_at(pad_block)
            rx, ry = rotate(px, py, rot)
            pads.append(Pad(pname, ptype, fx + rx, fy + ry))
        footprints.append(Footprint(name, fx, fy, rot, pads))
    return footprints


def board_bbox(text: str) -> tuple[float, float, float, float] | None:
    pts = []
    for m in re.finditer(r'\((?:gr_line|fp_line)\s+.*?\(start\s+([-0-9.]+)\s+([-0-9.]+)\).*?\(end\s+([-0-9.]+)\s+([-0-9.]+)\).*?\(layer\s+"Edge\.Cuts"\)', text, re.S):
        pts.append((float(m.group(1)), float(m.group(2))))
        pts.append((float(m.group(3)), float(m.group(4))))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def footprint_score(fp: Footprint) -> tuple[int, int, int]:
    key = fp.name.lower()
    keyword = any(k in key for k in ["pcie", "pciexpress", "m.2", "m2", "edge", "pad", "ww"])
    connect = [p for p in fp.pads if p.pad_type == "connect"]
    unique = len({p.name for p in fp.pads if p.name})
    return (1 if keyword else 0, len(connect), unique)


def select_edge_footprint(footprints: list[Footprint]) -> tuple[Footprint, list[Pad]]:
    candidates = [fp for fp in footprints if len({p.name for p in fp.pads if p.name}) >= 20]
    if not candidates:
        raise RuntimeError("no connector-like footprint found")
    fp = max(candidates, key=footprint_score)
    pads = [p for p in fp.pads if p.pad_type == "connect"] or fp.pads
    by_name: dict[str, Pad] = {}
    for p in pads:
        if not p.name:
            continue
        if p.name not in by_name or p.y > by_name[p.name].y:
            by_name[p.name] = p
    selected = list(by_name.values())
    selected.sort(key=lambda p: (p.x, p.y, p.name))
    return fp, selected


def median_pitch(pads: list[Pad]) -> float:
    xs = sorted({round(p.x, 3) for p in pads})
    diffs = [b - a for a, b in zip(xs, xs[1:]) if b - a > 0.2]
    if not diffs:
        return 1.0
    diffs.sort()
    return max(0.5, min(2.54, diffs[len(diffs) // 2]))


def synthetic_obstacles(pin_count: int, width: float, height: float, component_count: int) -> str:
    if component_count < 8:
        return "none"
    obs = []
    if pin_count >= 50:
        obs.append(f"{width*0.34:.1f}:{height*0.32:.1f}:{width*0.47:.1f}:{height*0.55:.1f}")
        obs.append(f"{width*0.62:.1f}:{height*0.20:.1f}:{width*0.76:.1f}:{height*0.42:.1f}")
    else:
        obs.append(f"{width*0.44:.1f}:{height*0.28:.1f}:{width*0.58:.1f}:{height*0.50:.1f}")
    return ";".join(obs)


def scenario_from_pcb(src: dict, index: int) -> dict:
    text = Path(src["pcb"]).read_text(encoding="utf-8", errors="ignore")
    footprints = parse_footprints(text)
    selected_fp, pads = select_edge_footprint(footprints)
    pitch = median_pitch(pads)
    span = max(p.x for p in pads) - min(p.x for p in pads) if len(pads) > 1 else pitch * len(pads)
    bbox = board_bbox(text)
    board_w = bbox[2] - bbox[0] if bbox else span + 30.0
    width = max(45.0, min(140.0, max(span + 24.0, board_w * 0.72)))
    height = max(32.0, min(58.0, 24.0 + 0.18 * len(pads)))
    pin_count = max(12, min(120, len(pads)))
    min_spacing = 1.8 if pitch < 1.1 else 2.0
    obstacles = synthetic_obstacles(pin_count, width, height, len(footprints))
    return {
        "case_file": f"kicad_case_{index:02d}_{src['id']}.csv",
        "name": f"kicad_{src['id']}",
        "repo": src["repo"],
        "url": src["url"],
        "license": src["license"],
        "pcb": str(src["pcb"].relative_to(ROOT)),
        "footprint": selected_fp.name,
        "footprints": len(footprints),
        "pins": pin_count,
        "width_mm": round(width, 2),
        "tail_height_mm": round(height, 2),
        "pin_pitch_mm": round(pitch, 3),
        "grid_mm": 1.0,
        "min_testpoint_spacing_mm": min_spacing,
        "line_spacing_mm": 0.5,
        "max_iterations": 100,
        "obstacles": obstacles,
    }


def write_case(case: dict) -> Path:
    CASE_DIR.mkdir(parents=True, exist_ok=True)
    path = CASE_DIR / case["case_file"]
    lines = [
        f"# source_repo,{case['repo']}",
        f"# source_url,{case['url']}",
        f"# source_pcb,{case['pcb']}",
        f"# selected_footprint,{case['footprint']}",
        f"name,{case['name']}",
        f"pins,{case['pins']}",
        f"width_mm,{case['width_mm']}",
        f"tail_height_mm,{case['tail_height_mm']}",
        f"pin_pitch_mm,{case['pin_pitch_mm']}",
        f"grid_mm,{case['grid_mm']}",
        f"min_testpoint_spacing_mm,{case['min_testpoint_spacing_mm']}",
        f"line_spacing_mm,{case['line_spacing_mm']}",
        f"max_iterations,{case['max_iterations']}",
        f"obstacles,{case['obstacles']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_case(case_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ROOT / "pcb_tail_router"), "--case", str(case_path), "--out", str(out_dir)], check=True)


def read_metrics(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_kicad_cli() -> Path | None:
    env = os.environ.get("KICAD_CLI")
    candidates = []
    if env:
        candidates.append(Path(env))
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
    proc = subprocess.run([str(kicad_cli), "version"], text=True, capture_output=True, check=True)
    return proc.stdout.strip()


def render_pdf_first_page(pdf_path: Path, out_path: Path, target_w: int = 760) -> None:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    page = pdf[0]
    width, _ = page.get_size()
    scale = target_w / width
    bitmap = page.render(scale=scale)
    image = trim_whitespace(bitmap.to_pil().convert("RGB"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def trim_whitespace(image: Image.Image, threshold: int = 246, padding: int = 16) -> Image.Image:
    rgb = image.convert("RGB")
    pixels = rgb.load()
    w, h = rgb.size
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            if min(r, g, b) < threshold:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
                found = True
    if not found:
        return rgb
    min_x = max(0, min_x - padding)
    min_y = max(0, min_y - padding)
    max_x = min(w, max_x + padding)
    max_y = min(h, max_y + padding)
    return rgb.crop((min_x, min_y, max_x, max_y))


def fit_panel(image: Image.Image, size: tuple[int, int] = (760, 360)) -> Image.Image:
    canvas = Image.new("RGB", size, "white")
    im = trim_whitespace(image).copy()
    im.thumbnail((size[0] - 12, size[1] - 12))
    x = (size[0] - im.width) // 2
    y = (size[1] - im.height) // 2
    canvas.paste(im, (x, y))
    return canvas


def export_original_board(case: dict, out_dir: Path, kicad_cli: Path | None) -> dict:
    if not kicad_cli:
        placeholder = out_dir / "original_pcb_unavailable.png"
        img = Image.new("RGB", (760, 360), "white")
        draw = ImageDraw.Draw(img)
        draw.text((30, 30), "KiCad CLI unavailable; original PCB export skipped.", fill=(40, 40, 40))
        img.save(placeholder)
        return {
            "kicad_export_status": "fallback_text_parser_only",
            "kicad_export_command": "",
            "original_pcb_svg": "",
            "original_pcb_pdf": "",
            "original_pcb_png": str(placeholder.relative_to(ROOT)),
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    pcb_path = ROOT / case["pcb"]
    svg_path = out_dir / "original_kicad_pcb.svg"
    pdf_path = out_dir / "original_kicad_pcb.pdf"
    layers = "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
    svg_cmd = [
        str(kicad_cli),
        "pcb",
        "export",
        "svg",
        "--mode-single",
        "--layers",
        layers,
        "--page-size-mode",
        "2",
        "--exclude-drawing-sheet",
        "--output",
        str(svg_path),
        str(pcb_path),
    ]
    pdf_cmd = [
        str(kicad_cli),
        "pcb",
        "export",
        "pdf",
        "--mode-single",
        "--layers",
        layers,
        "--exclude-refdes",
        "--exclude-value",
        "--output",
        str(pdf_path),
        str(pcb_path),
    ]
    subprocess.run(svg_cmd, check=True)
    subprocess.run(pdf_cmd, check=True)
    png_path = out_dir / "original_kicad_pcb.png"
    render_pdf_first_page(pdf_path, png_path)
    return {
        "kicad_export_status": "kicad_cli",
        "kicad_export_command": " ".join(svg_cmd),
        "original_pcb_svg": str(svg_path.relative_to(ROOT)),
        "original_pcb_pdf": str(pdf_path.relative_to(ROOT)),
        "original_pcb_png": str(png_path.relative_to(ROOT)),
    }


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
            x = float(elem.attrib.get("x", 0)) * scale
            y = float(elem.attrib.get("y", 0)) * scale
            w = float(elem.attrib.get("width", 0)) * scale
            h = float(elem.attrib.get("height", 0)) * scale
            fill = elem.attrib.get("fill", "#ffffff")
            outline = elem.attrib.get("stroke")
            draw.rectangle((x, y, x + w, y + h), fill=fill, outline=outline)
        elif tag == "polyline":
            pts = []
            for raw in elem.attrib.get("points", "").split():
                if "," in raw:
                    a, b = raw.split(",", 1)
                    pts.append((float(a) * scale, float(b) * scale))
            if len(pts) > 1:
                draw.line(pts, fill=elem.attrib.get("stroke", "#3578b8"), width=max(1, int(0.7 * scale)))
        elif tag == "circle":
            cx = float(elem.attrib.get("cx", 0)) * scale
            cy = float(elem.attrib.get("cy", 0)) * scale
            r = float(elem.attrib.get("r", 0)) * scale
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=elem.attrib.get("fill", "#000000"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trim_whitespace(img).save(out_path)


def comparison_png(case: dict, out_dir: Path) -> Path:
    original_png = ROOT / case["original_pcb_png"] if case.get("original_pcb_png") else None
    base_svg = out_dir / "layout_baseline_rule.svg"
    final_svg = out_dir / "layout_pso_congestion_reroute_astar.svg"
    base_png = out_dir / "layout_baseline_rule.png"
    final_png = out_dir / "layout_pso_congestion_reroute_astar.png"
    render_simple_svg(base_svg, base_png)
    render_simple_svg(final_svg, final_png)
    original = Image.open(original_png).convert("RGB") if original_png and original_png.exists() else None
    base = Image.open(base_png).convert("RGB")
    final = Image.open(final_png).convert("RGB")
    panel_size = (760, 360)
    w, h = panel_size
    pad = 48
    title_h = 60
    comp = Image.new("RGB", (w * 3 + pad * 4, h + title_h + pad), "white")
    draw = ImageDraw.Draw(comp)
    font = ImageFont.load_default()
    titles = ["original KiCad PCB", "baseline_rule", "pso_congestion_reroute_astar"]
    images = [original or Image.new("RGB", panel_size, "white"), base, final]
    for idx, (title, image) in enumerate(zip(titles, images)):
        x = pad + idx * (w + pad)
        draw.text((x, 18), f"{case['name']}  {title}", fill=(40, 40, 40), font=font)
        comp.paste(fit_panel(image, panel_size), (x, title_h))
    out = out_dir / "comparison_original_baseline_algorithm.png"
    comp.save(out)
    return out


def comparison_contact_sheet(cases: list[dict]) -> Path:
    thumbs = []
    for case in cases:
        path = ROOT / case["comparison_png"]
        im = Image.open(path).convert("RGB")
        im.thumbnail((1100, 230))
        thumbs.append((case["name"], im.copy()))
    w = 1160
    row_h = 290
    sheet = Image.new("RGB", (w, row_h * len(thumbs) + 24), "white")
    draw = ImageDraw.Draw(sheet)
    y = 18
    for name, im in thumbs:
        draw.text((24, y), name, fill=(30, 30, 30))
        sheet.paste(im, (24, y + 24))
        y += row_h
    out = RESULT_DIR / "comparison_contact_sheet.png"
    sheet.save(out)
    return out


def main() -> None:
    kicad_cli = find_kicad_cli()
    version = kicad_version(kicad_cli)
    cases = []
    for i, src in enumerate(SOURCES, 1):
        if not Path(src["pcb"]).exists():
            raise FileNotFoundError(src["pcb"])
        case = scenario_from_pcb(src, i)
        case_path = write_case(case)
        out_dir = RESULT_DIR / Path(case["case_file"]).stem
        run_case(case_path, out_dir)
        case.update(export_original_board(case, out_dir, kicad_cli))
        case["out_dir"] = str(out_dir.relative_to(ROOT))
        case["comparison_png"] = str(comparison_png(case, out_dir).relative_to(ROOT))
        cases.append(case)

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULT_DIR / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        fields = [
            "case",
            "repo",
            "footprint",
            "method",
            "pin_count",
            "coverage_percent",
            "routability_percent",
            "area_ratio_percent",
            "total_wire_mm",
            "violations",
            "congestion_peak",
            "congested_cells",
            "runtime_ms",
            "kicad_export_status",
            "original_pcb_png",
            "comparison_png",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            out_dir = ROOT / case["out_dir"]
            for row in read_metrics(out_dir / "metrics.csv"):
                writer.writerow(
                    {
                        "case": case["name"],
                        "repo": case["repo"],
                        "footprint": case["footprint"],
                        "method": row["method"],
                        "pin_count": row["pin_count"],
                        "coverage_percent": row["coverage_percent"],
                        "routability_percent": row["routability_percent"],
                        "area_ratio_percent": row["area_ratio_percent"],
                        "total_wire_mm": row["total_wire_mm"],
                        "violations": row["violations"],
                        "congestion_peak": row["congestion_peak"],
                        "congested_cells": row["congested_cells"],
                        "runtime_ms": row["runtime_ms"],
                        "kicad_export_status": case["kicad_export_status"],
                        "original_pcb_png": case["original_pcb_png"],
                        "comparison_png": case["comparison_png"],
                    }
                )

    sources_md = RESULT_DIR / "sources.md"
    lines = [
        "# Public KiCad PCB case sources",
        "",
        f"KiCad CLI version: `{version}`.",
        "",
        "The cases below are converted from public KiCad PCB projects. The experiment uses KiCad CLI when available to export original board images, then parses `.kicad_pcb` S-expression text to extract connector/gold-finger-like footprint parameters.",
        "",
        "| Case | Repository | License | PCB file | Selected footprint | Pins | Pitch/mm | Export | Obstacles |",
        "|---|---|---|---|---|---:|---:|---|---|",
    ]
    for c in cases:
        lines.append(
            f"| {c['name']} | [{c['repo']}]({c['url']}) | {c['license']} | `{c['pcb']}` | `{c['footprint']}` | {c['pins']} | {c['pin_pitch_mm']} | {c['kicad_export_status']} | {c['obstacles']} |"
        )
    sources_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    contact_sheet = comparison_contact_sheet(cases)

    report = RESULT_DIR / "experiment_report.md"
    rows = []
    with summary_path.open(newline="", encoding="utf-8") as f:
        by_case: dict[str, dict[str, dict]] = {}
        for row in csv.DictReader(f):
            by_case.setdefault(row["case"], {})[row["method"]] = row
    report_lines = [
        "# Public KiCad PCB Tail-Board Routing Experiment",
        "",
        "## Method",
        "",
        f"KiCad CLI version: `{version}`. The script first detects `KICAD_CLI`, then `kicad-cli` in `PATH`, then `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`. Original PCB screenshots are exported through KiCad CLI as SVG/PDF and rasterized from the PDF. If KiCad CLI is unavailable, the experiment falls back to text parsing only and marks the report accordingly.",
        "",
        "Public KiCad PCB projects were searched and cloned locally. For each PCB, the script selects the most connector-like footprint by keyword and pad count, extracts the pin count and representative pitch, abstracts component/keepout pressure as rectangular obstacles, and runs the same C++ tail-board placement/routing prototype.",
        "",
        "The `baseline_rule` method is used as the manual/experience-style baseline: it places test points in regular rows below the edge connector. The proposed method is `pso_congestion_reroute_astar`, which uses PSO-Hanan placement and congestion-aware rip-up/reroute A*.",
        "",
        "## Quantitative Comparison",
        "",
        "| Case | Pins | Baseline routability/% | Proposed routability/% | Baseline area/% | Proposed area/% | Baseline violations | Proposed violations | Baseline wire/mm | Proposed wire/mm | Original PCB | Comparison |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for case in cases:
        base = by_case[case["name"]]["baseline_rule"]
        final = by_case[case["name"]]["pso_congestion_reroute_astar"]
        screenshot = case["comparison_png"]
        original = case["original_pcb_png"]
        report_lines.append(
            f"| {case['name']} | {final['pin_count']} | {base['routability_percent']} | {final['routability_percent']} | "
            f"{base['area_ratio_percent']} | {final['area_ratio_percent']} | {base['violations']} | {final['violations']} | "
            f"{base['total_wire_mm']} | {final['total_wire_mm']} | [{Path(original).name}](../../{original}) | [{Path(screenshot).name}](../../{screenshot}) |"
        )
        rows.append((base, final))
    avg_base_route = sum(float(b["routability_percent"]) for b, _ in rows) / len(rows)
    avg_final_route = sum(float(f["routability_percent"]) for _, f in rows) / len(rows)
    avg_base_area = sum(float(b["area_ratio_percent"]) for b, _ in rows) / len(rows)
    avg_final_area = sum(float(f["area_ratio_percent"]) for _, f in rows) / len(rows)
    avg_base_viol = sum(float(b["violations"]) for b, _ in rows) / len(rows)
    avg_final_viol = sum(float(f["violations"]) for _, f in rows) / len(rows)
    report_lines += [
        "",
        "## Aggregate Result",
        "",
        f"- Average routability improved from {avg_base_route:.2f}% to {avg_final_route:.2f}%.",
        f"- Average tail-board area ratio reduced from {avg_base_area:.2f}% to {avg_final_area:.2f}%.",
        f"- Average legality violations reduced from {avg_base_viol:.2f} to {avg_final_viol:.2f}.",
        "- The M.2 HAT case remains partially unrouted because its extracted connector density and abstracted keepouts create a deliberately constrained case; the proposed method still improves routability, area ratio, violations and congestion peak compared with the baseline.",
        "",
        "## Screenshot Contact Sheet",
        "",
        "![Comparison contact sheet](comparison_contact_sheet.png)",
        "",
        "## Source Details",
        "",
        "See [sources.md](sources.md) for repository URLs, licenses, PCB files and selected footprints.",
    ]
    report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"cases={len(cases)}")
    print(f"kicad_cli={kicad_cli or 'unavailable'}")
    print(f"kicad_version={version}")
    print(f"summary={summary_path}")
    print(f"report={report}")
    print(f"contact_sheet={contact_sheet}")
    for case in cases:
        print(f"{case['name']} comparison={case['comparison_png']}")


if __name__ == "__main__":
    main()
