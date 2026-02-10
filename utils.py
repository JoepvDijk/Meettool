import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def _shape_tool(obj: Dict[str, Any]) -> str:
    shape_type = str(obj.get("type", "")).lower()
    if "line" in shape_type:
        return "line"
    if "circle" in shape_type:
        return "circle"
    return "unknown"


def is_label_object(obj: Dict[str, Any]) -> bool:
    return bool(obj.get("isLabel", False)) or str(obj.get("type", "")).lower() in {"text", "textbox"}


def _extract_line_endpoints_canvas(obj: Dict[str, Any]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    scale_x = float(obj.get("scaleX", 1.0))
    scale_y = float(obj.get("scaleY", 1.0))
    left = float(obj.get("left", 0.0))
    top = float(obj.get("top", 0.0))

    x1 = float(obj.get("x1", 0.0)) * scale_x
    y1 = float(obj.get("y1", 0.0)) * scale_y
    x2 = float(obj.get("x2", 0.0)) * scale_x
    y2 = float(obj.get("y2", 0.0)) * scale_y

    # Fabric line endpoints are typically relative to object origin with left/top offset.
    return (left + x1, top + y1), (left + x2, top + y2)


def _extract_circle_canvas(obj: Dict[str, Any]) -> Tuple[float, float, float, float]:
    # Fabric circle uses left/top as top-left of bounding box.
    left = float(obj.get("left", 0.0))
    top = float(obj.get("top", 0.0))
    radius = float(obj.get("radius", 0.0))
    scale_x = float(obj.get("scaleX", 1.0))
    scale_y = float(obj.get("scaleY", 1.0))

    rx = abs(radius * scale_x)
    ry = abs(radius * scale_y)
    cx = left + rx
    cy = top + ry
    return cx, cy, rx, ry


def extract_geometry(obj: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Extract normalized geometry in canvas coordinates."""
    tool = _shape_tool(obj)

    if tool == "line":
        (x1, y1), (x2, y2) = _extract_line_endpoints_canvas(obj)
        return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2}

    if tool == "circle":
        cx, cy, rx, ry = _extract_circle_canvas(obj)
        return {"type": "circle", "cx": cx, "cy": cy, "rx": rx, "ry": ry}

    return None


def measurement_px_from_geometry(geom: Dict[str, float], scale_x: float, scale_y: float) -> float:
    """Compute measurement in image pixels from canvas geometry."""
    if geom["type"] == "line":
        dx = (geom["x2"] - geom["x1"]) * scale_x
        dy = (geom["y2"] - geom["y1"]) * scale_y
        return math.hypot(dx, dy)

    rx_img = geom["rx"] * scale_x
    ry_img = geom["ry"] * scale_y
    return 2.0 * ((rx_img + ry_img) / 2.0)


def label_anchor_canvas(geom: Dict[str, float]) -> Tuple[float, float]:
    """Return requested label anchor in canvas coordinates."""
    if geom["type"] == "line":
        return geom["x2"] + 12.0, geom["y2"] - 12.0

    r_eff = (geom["rx"] + geom["ry"]) / 2.0
    return geom["cx"] + r_eff + 12.0, geom["cy"] - r_eff - 12.0


def clamp_label_canvas(x: float, y: float, canvas_w: int, canvas_h: int, margin: int = 5) -> Tuple[float, float]:
    clamped_x = max(float(margin), min(x, float(canvas_w - margin)))
    clamped_y = max(float(margin), min(y, float(canvas_h - margin)))
    return clamped_x, clamped_y


def ensure_shape_ids(shapes: List[Dict[str, Any]], next_id: int) -> Tuple[List[Dict[str, Any]], int]:
    updated = []
    counter = next_id
    for obj in shapes:
        new_obj = dict(obj)
        if not new_obj.get("shapeId"):
            new_obj["shapeId"] = f"shape-{counter}"
            counter += 1
        updated.append(new_obj)
    return updated, counter


def make_label_object(shape_id: str, text: str, x: float, y: float, font_size: int) -> Dict[str, Any]:
    return {
        "type": "textbox",
        "text": text,
        "left": x,
        "top": y,
        "fill": "rgb(255,0,0)",
        "fontSize": font_size,
        "fontWeight": "bold",
        "selectable": False,
        "evented": False,
        "editable": False,
        "hasControls": False,
        "hasBorders": False,
        "lockMovementX": True,
        "lockMovementY": True,
        "isLabel": True,
        "labelForId": shape_id,
    }


def build_measurements_and_labels(
    shapes: List[Dict[str, Any]],
    scale_um_per_px: float,
    scale_x: float,
    scale_y: float,
    canvas_w: int,
    canvas_h: int,
    font_size: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, float]]]:
    measurements: List[Dict[str, Any]] = []
    labels: List[Dict[str, Any]] = []
    circle_debug: List[Dict[str, float]] = []

    for idx, shape in enumerate(shapes, start=1):
        geom = extract_geometry(shape)
        if not geom:
            continue

        measurement_px = measurement_px_from_geometry(geom, scale_x, scale_y)
        if measurement_px <= 0:
            continue

        measurement_um = measurement_px * scale_um_per_px
        anchor_x, anchor_y = label_anchor_canvas(geom)
        label_x, label_y = clamp_label_canvas(anchor_x, anchor_y, canvas_w, canvas_h, margin=5)

        tool = "Line" if geom["type"] == "line" else "Circle"
        measurements.append(
            {
                "index": idx,
                "shape_id": shape.get("shapeId", ""),
                "tool": tool,
                "measurement_px": measurement_px,
                "measurement_um": measurement_um,
            }
        )

        labels.append(
            make_label_object(
                shape_id=str(shape.get("shapeId", f"shape-{idx}")),
                text=f"{measurement_um:.2f} µm",
                x=label_x,
                y=label_y,
                font_size=font_size,
            )
        )

        if geom["type"] == "circle" and not circle_debug:
            circle_debug.append(
                {
                    "left": float(shape.get("left", 0.0)),
                    "top": float(shape.get("top", 0.0)),
                    "radius": float(shape.get("radius", 0.0)),
                    "scaleX": float(shape.get("scaleX", 1.0)),
                    "scaleY": float(shape.get("scaleY", 1.0)),
                    "cx": geom["cx"],
                    "cy": geom["cy"],
                    "rx": geom["rx"],
                    "ry": geom["ry"],
                }
            )

    return measurements, labels, circle_debug


def split_shapes_and_labels(objects: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    shapes: List[Dict[str, Any]] = []
    labels: List[Dict[str, Any]] = []
    for obj in objects:
        if is_label_object(obj):
            labels.append(obj)
        else:
            if _shape_tool(obj) in {"line", "circle"}:
                shapes.append(obj)
    return shapes, labels


def csv_rows(filename: str, measurements: List[Dict[str, Any]], scale_um_per_px: float) -> str:
    timestamp = datetime.now().isoformat(timespec="seconds")
    header = "filename,tool,length_px/diameter_px,length_um/diameter_um,scale_um_per_px,timestamp\n"
    lines = [header]
    for m in measurements:
        lines.append(
            f"{filename},{m['tool']},{m['measurement_px']:.4f},{m['measurement_um']:.4f},{scale_um_per_px:.9f},{timestamp}\n"
        )
    return "".join(lines)
