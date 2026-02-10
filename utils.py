import json
import math
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

SETTINGS_FILE = Path("settings.json")


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
    """Best-effort line length extraction from Fabric.js-like object."""
    # Common direct endpoint format.
    if all(k in obj for k in ("x1", "y1", "x2", "y2")):
        return math.hypot(float(obj["x2"]) - float(obj["x1"]), float(obj["y2"]) - float(obj["y1"]))

    # Fallback for line represented by bounding box + scaling.
    width = float(obj.get("width", 0.0))
    height = float(obj.get("height", 0.0))
    scale_x = float(obj.get("scaleX", 1.0))
    scale_y = float(obj.get("scaleY", 1.0))
    return math.hypot(width * scale_x, height * scale_y)


def measurement_from_canvas_object(obj: dict, tool: str) -> float:
    """Return measurement in px based on selected tool.

    For Line tool: returns length_px.
    For Circle tool: returns diameter_px.
    """
    if tool == "Line":
        return _line_length_from_obj(obj)

    # Circle in Fabric.js usually has radius and scaleX/scaleY.
    radius = float(obj.get("radius", 0.0))
    scale_x = float(obj.get("scaleX", 1.0))
    scale_y = float(obj.get("scaleY", 1.0))
    scale = (scale_x + scale_y) / 2 if (scale_x > 0 and scale_y > 0) else 1.0
    return 2.0 * radius * scale


def label_position_from_object(obj: dict, tool: str) -> tuple[float, float]:
    """Pick a reasonable text position near object for annotation."""
    left = float(obj.get("left", 0.0))
    top = float(obj.get("top", 0.0))

    if tool == "Line":
        # Prefer midpoint if endpoints are available.
        if all(k in obj for k in ("x1", "y1", "x2", "y2")):
            mid_x = (float(obj["x1"]) + float(obj["x2"])) / 2
            mid_y = (float(obj["y1"]) + float(obj["y2"])) / 2
            return mid_x + 8, mid_y - 8
        return left + 8, top - 8

    # Circle.
    radius = float(obj.get("radius", 0.0)) * float(obj.get("scaleX", 1.0))
    return left + radius + 8, top - 8


def _line_endpoints_for_draw(obj: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    if all(k in obj for k in ("x1", "y1", "x2", "y2")):
        return (float(obj["x1"]), float(obj["y1"])), (float(obj["x2"]), float(obj["y2"]))

    left = float(obj.get("left", 0.0))
    top = float(obj.get("top", 0.0))
    width = float(obj.get("width", 0.0)) * float(obj.get("scaleX", 1.0))
    height = float(obj.get("height", 0.0)) * float(obj.get("scaleY", 1.0))
    return (left, top), (left + width, top + height)


def create_annotated_image(
    base_image: Image.Image,
    obj: dict,
    tool: str,
    label_text: str,
) -> bytes:
    """Draw selected shape and label onto image and return PNG bytes."""
    image = base_image.convert("RGB").copy()
    draw = ImageDraw.Draw(image)

    color = (255, 0, 0)
    stroke = 3

    if tool == "Line":
        start, end = _line_endpoints_for_draw(obj)
        draw.line([start, end], fill=color, width=stroke)
    else:
        cx = float(obj.get("left", 0.0))
        cy = float(obj.get("top", 0.0))
        radius_x = float(obj.get("radius", 0.0)) * float(obj.get("scaleX", 1.0))
        radius_y = float(obj.get("radius", 0.0)) * float(obj.get("scaleY", 1.0))
        draw.ellipse(
            [cx - radius_x, cy - radius_y, cx + radius_x, cy + radius_y],
            outline=color,
            width=stroke,
        )

    tx, ty = label_position_from_object(obj, tool)
    draw.text((tx, ty), label_text, fill=color)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def csv_row(
    filename: str,
    tool: str,
    measurement_px: float,
    measurement_um: float,
    scale_um_per_px: float,
) -> str:
    timestamp = datetime.now().isoformat(timespec="seconds")
    return (
        "filename,tool,length_px/diameter_px,length_um/diameter_um,scale_um_per_px,timestamp\n"
        f"{filename},{tool},{measurement_px:.4f},{measurement_um:.4f},{scale_um_per_px:.9f},{timestamp}\n"
    )
