import json
import math
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SETTINGS_FILE = Path("settings.json")
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Helvetica.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def load_scale(default_scale: float) -> float:
    """Load saved scale from settings.json if present and valid."""
    if not SETTINGS_FILE.exists():
        return default_scale

    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        scale = float(data.get("scale_um_per_px", default_scale))
        if scale > 0:
            return scale
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass

    return default_scale


def save_scale(scale_um_per_px: float) -> None:
    """Persist scale value to settings.json."""
    SETTINGS_FILE.write_text(
        json.dumps({"scale_um_per_px": scale_um_per_px}, indent=2),
        encoding="utf-8",
    )


def _line_length_from_obj(obj: dict) -> float:
    """Best-effort line length extraction from Fabric.js-like object in canvas px."""
    geom = extract_geometry(obj)
    if not geom or geom["type"] != "line":
        return 0.0
    return compute_measurement(geom)


def measurement_from_canvas_object(obj: dict, tool: str) -> float:
    """Return measurement in px based on selected tool (canvas px)."""
    geom = extract_geometry(obj)
    if not geom:
        return 0.0

    if tool == "Line" and geom["type"] == "line":
        return compute_measurement(geom)
    if tool == "Circle" and geom["type"] == "circle":
        return compute_measurement(geom)
    return 0.0


def _shape_tool(obj: dict) -> str:
    forced_tool = str(obj.get("__tool", "")).lower()
    if forced_tool in {"line", "circle"}:
        return forced_tool

    shape_type = str(obj.get("type", "")).lower()
    if "line" in shape_type:
        return "line"
    if "circle" in shape_type:
        return "circle"

    if all(k in obj for k in ("x1", "y1", "x2", "y2")):
        return "line"
    if "radius" in obj:
        return "circle"
    return "unknown"


def _extract_line_endpoints_canvas(obj: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    scale_x = float(obj.get("scaleX", 1.0))
    scale_y = float(obj.get("scaleY", 1.0))
    left = float(obj.get("left", 0.0))
    top = float(obj.get("top", 0.0))
    width = abs(float(obj.get("width", 0.0)) * scale_x)
    height = abs(float(obj.get("height", 0.0)) * scale_y)

    x1 = float(obj.get("x1", 0.0)) * scale_x
    y1 = float(obj.get("y1", 0.0)) * scale_y
    x2 = float(obj.get("x2", 0.0)) * scale_x
    y2 = float(obj.get("y2", 0.0)) * scale_y

    origin_x = str(obj.get("originX", "left")).lower()
    origin_y = str(obj.get("originY", "top")).lower()

    # Heuristic A: points are already absolute in canvas coordinates.
    raw_start = (x1, y1)
    raw_end = (x2, y2)

    # Heuristic B: points are relative to object position.
    rel_start = (left + x1, top + y1)
    rel_end = (left + x2, top + y2)

    # Heuristic C: points are relative to object center.
    center_x = left if origin_x == "center" else left + width / 2.0
    center_y = top if origin_y == "center" else top + height / 2.0
    ctr_start = (center_x + x1, center_y + y1)
    ctr_end = (center_x + x2, center_y + y2)

    candidates = [(raw_start, raw_end), (rel_start, rel_end), (ctr_start, ctr_end)]

    def _score(pair: tuple[tuple[float, float], tuple[float, float]]) -> float:
        (ax, ay), (bx, by) = pair
        length = math.hypot(bx - ax, by - ay)
        if length <= 0:
            return -1e9
        penalty = 0.0
        for px, py in (pair[0], pair[1]):
            if px < -50 or py < -50:
                penalty += 200.0
        return length - penalty

    return max(candidates, key=_score)


def _extract_circle_canvas(obj: dict) -> tuple[float, float, float]:
    left = float(obj.get("left", 0.0))
    top = float(obj.get("top", 0.0))
    radius = float(obj.get("radius", 0.0))
    scale_x = float(obj.get("scaleX", 1.0))
    scale_y = float(obj.get("scaleY", 1.0))

    rx = radius * scale_x
    ry = radius * scale_y
    r = (abs(rx) + abs(ry)) / 2.0

    origin_x = str(obj.get("originX", "left")).lower()
    origin_y = str(obj.get("originY", "top")).lower()

    if origin_x == "center":
        cx = left
    else:
        cx = left + rx

    if origin_y == "center":
        cy = top
    else:
        cy = top + ry

    return cx, cy, abs(r)


def extract_geometry(obj: dict):
    """Extract normalized geometry in canvas coordinates."""
    tool = _shape_tool(obj)
    if tool == "line":
        start, end = _extract_line_endpoints_canvas(obj)
        return {
            "type": "line",
            "x1": float(start[0]),
            "y1": float(start[1]),
            "x2": float(end[0]),
            "y2": float(end[1]),
        }

    if tool == "circle":
        cx, cy, r = _extract_circle_canvas(obj)
        return {
            "type": "circle",
            "cx": float(cx),
            "cy": float(cy),
            "r": float(r),
        }

    return None


def compute_measurement(geom: dict) -> float:
    """Return line length or circle diameter in pixels for provided geometry."""
    if geom["type"] == "line":
        return math.hypot(geom["x2"] - geom["x1"], geom["y2"] - geom["y1"])
    if geom["type"] == "circle":
        return 2.0 * geom["r"]
    return 0.0


def _geometry_to_image_space(geom: dict, canvas_to_img_scale: tuple[float, float]) -> dict:
    sx, sy = canvas_to_img_scale
    if geom["type"] == "line":
        return {
            "type": "line",
            "x1": geom["x1"] * sx,
            "y1": geom["y1"] * sy,
            "x2": geom["x2"] * sx,
            "y2": geom["y2"] * sy,
        }

    # keep circles visually circular when aspect ratio is preserved; average if tiny rounding differs
    avg_s = (sx + sy) / 2.0
    return {
        "type": "circle",
        "cx": geom["cx"] * sx,
        "cy": geom["cy"] * sy,
        "r": geom["r"] * avg_s,
    }


def _get_font_for_size(size: int) -> tuple[ImageFont.ImageFont, str, bool]:
    for path_str in FONT_CANDIDATES:
        path = Path(path_str)
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size=size), str(path), False
        except OSError:
            continue
    return ImageFont.load_default(), "default", True


def get_annotation_debug_info(img_w: int) -> dict:
    """Expose font sizing/loading details for UI debugging."""
    font_size = max(60, int(img_w * 0.05))
    _, font_path, is_default = _get_font_for_size(font_size)
    return {
        "font_size": font_size,
        "font_path": font_path,
        "font_is_default": is_default,
    }


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top
    except AttributeError:
        return draw.textsize(text, font=font)


def _clamp_label(
    x: float,
    y: float,
    text_size: tuple[int, int],
    image_size: tuple[int, int],
    margin: int = 5,
) -> tuple[float, float]:
    text_w, text_h = text_size
    img_w, img_h = image_size
    max_x = max(float(margin), float(img_w - text_w - margin))
    max_y = max(float(margin), float(img_h - text_h - margin))
    clamped_x = max(float(margin), min(x, max_x))
    clamped_y = max(float(margin), min(y, max_y))
    return clamped_x, clamped_y


def _label_for_measurement(geom_type: str, measurement_um: float) -> str:
    return f"{measurement_um:.2f} µm"


def annotate_image(
    img_pil: Image.Image,
    objects: list[dict],
    scale_um_per_px: float,
    canvas_to_img_scale: tuple[float, float],
) -> Image.Image:
    """Draw all shapes and labels on full-resolution image."""
    image = img_pil.convert("RGB").copy()
    draw = ImageDraw.Draw(image)

    img_w, _ = image.size
    font_size = max(60, int(img_w * 0.05))
    font, _, _ = _get_font_for_size(font_size)

    stroke = 5
    color = (255, 0, 0)
    for obj in objects:
        geom = extract_geometry(obj)
        if not geom:
            continue

        geom_img = _geometry_to_image_space(geom, canvas_to_img_scale)
        measurement_px = compute_measurement(geom_img)
        if measurement_px <= 0:
            continue
        measurement_um = measurement_px * scale_um_per_px
        label_text = _label_for_measurement(geom_img["type"], measurement_um)

        if geom_img["type"] == "line":
            x1 = geom_img["x1"]
            y1 = geom_img["y1"]
            x2 = geom_img["x2"]
            y2 = geom_img["y2"]
            draw.line([(x1, y1), (x2, y2)], fill=color, width=stroke)
            label_x = x2 + 12
            label_y = y2 - 12
        else:
            cx = geom_img["cx"]
            cy = geom_img["cy"]
            r = geom_img["r"]
            draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=color, width=stroke)
            label_x = cx + r + 12
            label_y = cy - r - 12

        text_w, text_h = _text_size(draw, label_text, font)
        tx, ty = _clamp_label(label_x, label_y, (text_w, text_h), image.size, margin=5)
        draw.text((tx, ty), label_text, fill=color, font=font)

    return image


def create_annotated_image(
    base_image: Image.Image,
    objects: list[dict],
    scale_um_per_px: float,
    canvas_to_img_scale: tuple[float, float],
) -> bytes:
    """Return annotated image as PNG bytes."""
    image = annotate_image(base_image, objects, scale_um_per_px, canvas_to_img_scale)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def csv_rows(
    filename: str,
    measurements: list[dict],
    scale_um_per_px: float,
) -> str:
    """Build CSV rows for all measurements."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    header = "filename,tool,length_px/diameter_px,length_um/diameter_um,scale_um_per_px,timestamp\n"
    lines = [header]
    for m in measurements:
        lines.append(
            f"{filename},{m['tool']},{m['measurement_px']:.4f},{m['measurement_um']:.4f},{scale_um_per_px:.9f},{timestamp}\n"
        )
    return "".join(lines)


def csv_row(
    filename: str,
    tool: str,
    measurement_px: float,
    measurement_um: float,
    scale_um_per_px: float,
) -> str:
    """Backwards-compatible single-row CSV helper."""
    return csv_rows(
        filename,
        [{"tool": tool, "measurement_px": measurement_px, "measurement_um": measurement_um}],
        scale_um_per_px,
    )
