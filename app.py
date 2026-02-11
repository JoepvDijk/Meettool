from io import BytesIO, StringIO
from uuid import uuid4

import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from utils import (
    clamp_label_canvas,
    csv_rows,
    extract_geometry,
    label_anchor_canvas,
    load_scale,
    measurement_px_from_geometry,
    save_scale,
)

DEFAULT_SCALE = 1.342281879  # 400 µm / 298 px
MAX_W = 1100
MAX_H = 650
PALETTE = {
    "red": "#ff0000",
    "blue": "#0066ff",
    "yellow": "#ffd400",
    "green": "#00b050",
    "purple": "#7f00ff",
    "orange": "#ff7a00",
}
COLOR_LABEL_TO_KEY = {
    "Red": "red",
    "Blue": "blue",
    "Yellow": "yellow",
    "Green": "green",
    "Purple": "purple",
    "Orange": "orange",
}
COLOR_KEY_TO_LABEL = {v: k for k, v in COLOR_LABEL_TO_KEY.items()}

st.set_page_config(page_title="Microscope Measurement Tool", layout="wide")
st.title("Microscope Measurement Tool")
st.markdown(
    """
<style>
  .block-container { padding-left: 2rem; padding-right: 2rem; }
</style>
""",
    unsafe_allow_html=True,
)

if "scale_um_per_px" not in st.session_state:
    st.session_state.scale_um_per_px = load_scale(DEFAULT_SCALE)
if "bg_bytes" not in st.session_state:
    st.session_state.bg_bytes = b""
if "canvas_source_file" not in st.session_state:
    st.session_state.canvas_source_file = ""
if "shapes" not in st.session_state:
    st.session_state.shapes = []
if "labels_by_shape_id" not in st.session_state:
    st.session_state.labels_by_shape_id = {}
if "calibration_mode" not in st.session_state:
    st.session_state.calibration_mode = False
if "display_scale" not in st.session_state:
    st.session_state.display_scale = 1.0

uploaded_file = st.file_uploader("Upload image", type=["png", "jpg", "jpeg"])
draw_tool = st.radio("Draw tool", ["Line", "Circle"], horizontal=True)

with st.sidebar:
    st.header("Settings")
    st.session_state.scale_um_per_px = st.number_input(
        "Scale (µm per pixel)",
        min_value=0.000000001,
        value=float(st.session_state.scale_um_per_px),
        format="%.9f",
    )

    st.subheader("Calibrate scale")
    if st.button("Enter calibration mode"):
        st.session_state.calibration_mode = True

    known_length_um = st.number_input(
        "Known length (µm)",
        min_value=0.000000001,
        value=400.0,
        format="%.4f",
    )

if not uploaded_file:
    st.info("Upload an image to start measuring.")
    st.stop()

if st.session_state.canvas_source_file != uploaded_file.name:
    st.session_state.canvas_source_file = uploaded_file.name
    st.session_state.bg_bytes = uploaded_file.getvalue()
    st.session_state.shapes = []
    st.session_state.labels_by_shape_id = {}

if not st.session_state.bg_bytes:
    st.session_state.bg_bytes = uploaded_file.getvalue()

image = Image.open(BytesIO(st.session_state.bg_bytes)).convert("RGB")
img_w, img_h = image.size
scale_w = float(MAX_W) / float(img_w)
scale_h = float(MAX_H) / float(img_h)
display_scale = min(1.0, scale_w, scale_h)
CANVAS_W = int(img_w * display_scale)
CANVAS_H = int(img_h * display_scale)
st.session_state.display_scale = display_scale
display_image = image.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)

# ----------------------------
# Canvas 1: draw vector shapes
# ----------------------------
st.subheader("Canvas 1: Draw Shapes")
if st.session_state.calibration_mode:
    st.warning("Calibration mode enabled: draw one LINE over the known scale bar.")
    draw_mode = "line"
else:
    draw_mode = "line" if draw_tool == "Line" else "circle"

with st.container():
    draw_canvas = st_canvas(
        fill_color="rgba(255, 0, 0, 0.0)",
        stroke_width=2,
        stroke_color="#ff0000",
        background_image=display_image,
        height=CANVAS_H,
        width=CANVAS_W,
        drawing_mode=draw_mode,
        initial_drawing={"version": "4.4.0", "objects": st.session_state.shapes},
        update_streamlit=True,
        key="draw_canvas",
    )

live_draw_objects = []
if draw_canvas.json_data and "objects" in draw_canvas.json_data:
    live_draw_objects = draw_canvas.json_data["objects"]

if live_draw_objects:
    # Keep stable ids; if incoming object lost id, reuse by index where possible.
    prev_shapes = st.session_state.shapes
    prev_shapes_by_id = {str(s.get("id", "")): s for s in prev_shapes if s.get("id")}
    synced_shapes = []
    for idx, obj in enumerate(live_draw_objects):
        shape = dict(obj)
        shape_id = str(shape.get("id", "")).strip()
        if not shape_id and idx < len(prev_shapes):
            prev_id = str(prev_shapes[idx].get("id", "")).strip()
            if prev_id:
                shape_id = prev_id
        if not shape_id:
            shape_id = f"shape_{uuid4()}"
        shape["id"] = shape_id
        prev_shape = prev_shapes_by_id.get(shape_id, {})
        color_key = str(shape.get("color", prev_shape.get("color", "red"))).lower()
        if color_key not in PALETTE:
            color_key = "red"
        shape["color"] = color_key
        shape["stroke"] = PALETTE[color_key]
        if str(shape.get("type", "")).lower() == "circle":
            shape["fill"] = str(shape.get("fill", "rgba(0,0,0,0)"))
        synced_shapes.append(shape)
    if synced_shapes != st.session_state.shapes:
        st.session_state.shapes = synced_shapes

shapes = st.session_state.shapes
if not shapes:
    st.info("Draw a shape to continue.")
    st.stop()

# ----------------------------------
# Measurements + reusable label store
# ----------------------------------
measurements = []
current_shape_ids = []
for idx, shape in enumerate(shapes, start=1):
    geom = extract_geometry(shape)
    if not geom:
        continue

    # Canvas coordinates are in display pixels; convert back to original pixels.
    measurement_px_display = measurement_px_from_geometry(geom, 1.0, 1.0)
    measurement_px = measurement_px_display / max(display_scale, 1e-12)
    if measurement_px <= 0:
        continue

    measurement_um = measurement_px * st.session_state.scale_um_per_px
    tool = "Line" if geom["type"] == "line" else "Circle"
    shape_id = str(shape.get("id", f"shape_{idx}"))
    current_shape_ids.append(shape_id)

    measurements.append(
        {
            "index": idx,
            "shape_id": shape_id,
            "tool": tool,
            "measurement_px": measurement_px,
            "measurement_um": measurement_um,
            "color": str(shape.get("color", "red")),
        }
    )

    label = st.session_state.labels_by_shape_id.get(shape_id)
    if label is None:
        ax, ay = label_anchor_canvas(geom)
        lx, ly = clamp_label_canvas(ax, ay, CANVAS_W, CANVAS_H, margin=5)
        st.session_state.labels_by_shape_id[shape_id] = {
            "type": "textbox",
            "text": f"{measurement_um:.2f} µm",
            "left": lx,
            "top": ly,
            "fontSize": 50,
            "fill": PALETTE.get(str(shape.get("color", "red")), "#ff0000"),
            "selectable": True,
            "evented": True,
            "editable": True,
            "hasControls": True,
            "hasBorders": True,
            "isLabel": True,
            "labelId": f"label_{shape_id}",
            "forShapeId": shape_id,
            "id": f"label_{shape_id}",
        }
    else:
        # Reuse existing position/size; only refresh text.
        label["text"] = f"{measurement_um:.2f} µm"
        label["fill"] = PALETTE.get(str(shape.get("color", "red")), "#ff0000")

# Remove labels for deleted shapes.
for stored_shape_id in list(st.session_state.labels_by_shape_id.keys()):
    if stored_shape_id not in current_shape_ids:
        del st.session_state.labels_by_shape_id[stored_shape_id]

if not measurements:
    st.info("No valid measurable shapes found yet.")
    st.stop()

if st.session_state.calibration_mode:
    line_rows = [m for m in measurements if m["tool"] == "Line"]
    if not line_rows:
        st.info("Calibration mode needs at least one line.")
    else:
        latest_line = line_rows[-1]
        line_px = latest_line["measurement_px"]
        if line_px <= 0:
            st.error("Invalid calibration: line length must be greater than 0 px.")
        else:
            calibrated_scale = known_length_um / line_px
            st.caption(f"Calibration line (latest): {line_px:.2f} px -> {calibrated_scale:.9f} µm/px")
            if st.button("Save scale"):
                st.session_state.scale_um_per_px = calibrated_scale
                save_scale(calibrated_scale)
                st.success("Scale saved to settings.json")
                st.session_state.calibration_mode = False

# -------------------------------------
# Canvas 2: same background + same shapes
# -------------------------------------
label_objects = list(st.session_state.labels_by_shape_id.values())
canvas2_objects = shapes + label_objects

st.subheader("Canvas 2: Drag Labels On Preview")
with st.container():
    label_canvas = st_canvas(
        fill_color="rgba(255, 0, 0, 0.0)",
        stroke_width=2,
        stroke_color="#ff0000",
        background_image=display_image,
        height=CANVAS_H,
        width=CANVAS_W,
        drawing_mode="transform",
        initial_drawing={"version": "4.4.0", "objects": canvas2_objects},
        update_streamlit=True,
        key="label_canvas",
    )

if st.button("Apply label positions"):
    if label_canvas.json_data and "objects" in label_canvas.json_data:
        live_objects = label_canvas.json_data["objects"]
        # Overwrite label state by id (dedup by labelId/forShapeId).
        for obj in live_objects:
            if not obj.get("isLabel"):
                continue
            shape_id = str(obj.get("forShapeId", "")).strip()
            if not shape_id:
                continue
            label_id = str(obj.get("labelId", f"label_{shape_id}")).strip()
            st.session_state.labels_by_shape_id[shape_id] = {
                "type": "textbox",
                "text": str(obj.get("text", "")),
                "left": float(obj.get("left", 0.0)),
                "top": float(obj.get("top", 0.0)),
                "fontSize": float(obj.get("fontSize", 50)),
                "fill": str(obj.get("fill", "rgb(255,0,0)")),
                "scaleX": float(obj.get("scaleX", 1.0)),
                "scaleY": float(obj.get("scaleY", 1.0)),
                "angle": float(obj.get("angle", 0.0)),
                "width": float(obj.get("width", 200.0)),
                "height": float(obj.get("height", 60.0)),
                "selectable": True,
                "evented": True,
                "editable": True,
                "hasControls": True,
                "hasBorders": True,
                "isLabel": True,
                "labelId": label_id,
                "forShapeId": shape_id,
                "id": label_id,
            }
        st.success("Label positions applied")

# Download from Canvas 2 raster output (contains same vector objects rendered).
if label_canvas.image_data is not None:
    out_image = Image.fromarray(label_canvas.image_data.astype("uint8"), mode="RGBA")
    out_buf = BytesIO()
    out_image.save(out_buf, format="PNG")
    st.download_button(
        "Download annotated PNG",
        data=out_buf.getvalue(),
        file_name=f"annotated_{uploaded_file.name.rsplit('.', 1)[0]}.png",
        mime="image/png",
    )

st.caption(
    f"Debug: original=({img_w}x{img_h}) | display=({CANVAS_W}x{CANVAS_H}) | "
    f"display_scale={display_scale:.4f} | shapes={len(shapes)} | labels={len(label_objects)}"
)

table_rows = []
for m in measurements:
    metric = "Length" if m["tool"] == "Line" else "Diameter"
    table_rows.append(
        {
            "shape_id": m["shape_id"],
            "#": m["index"],
            "Tool": m["tool"],
            "Metric": metric,
            "Pixels": round(m["measurement_px"], 2),
            "µm": round(m["measurement_um"], 2),
            "Color": COLOR_KEY_TO_LABEL.get(str(m.get("color", "red")), "Red"),
        }
    )

table_df = pd.DataFrame(table_rows)
edited_df = st.data_editor(
    table_df,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Color": st.column_config.SelectboxColumn("Color", options=list(COLOR_LABEL_TO_KEY.keys()))
    },
    disabled=["shape_id", "#", "Tool", "Metric", "Pixels", "µm"],
    key="measurements_editor",
)

edited_shape_colors = {}
for _, row in edited_df.iterrows():
    sid = str(row["shape_id"])
    color_key = COLOR_LABEL_TO_KEY.get(str(row["Color"]), "red")
    edited_shape_colors[sid] = color_key

shapes_color_changed = False
for shape in st.session_state.shapes:
    sid = str(shape.get("id", ""))
    if not sid:
        continue
    new_color = edited_shape_colors.get(sid, str(shape.get("color", "red")))
    if new_color not in PALETTE:
        new_color = "red"
    if str(shape.get("color", "red")) != new_color:
        shape["color"] = new_color
        shape["stroke"] = PALETTE[new_color]
        if str(shape.get("type", "")).lower() == "circle":
            shape["fill"] = str(shape.get("fill", "rgba(0,0,0,0)"))
        label_obj = st.session_state.labels_by_shape_id.get(sid)
        if label_obj:
            label_obj["fill"] = PALETTE[new_color]
        shapes_color_changed = True

if shapes_color_changed:
    st.session_state.shapes = [dict(s) for s in st.session_state.shapes]

csv_data = csv_rows(
    filename=uploaded_file.name,
    measurements=measurements,
    scale_um_per_px=st.session_state.scale_um_per_px,
)
st.download_button(
    "Download measurements CSV",
    data=StringIO(csv_data).getvalue(),
    file_name="measurement.csv",
    mime="text/csv",
)
