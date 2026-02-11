from io import BytesIO, StringIO
from uuid import uuid4

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
    render_base,
    render_final_with_labels,
    save_scale,
)

DEFAULT_SCALE = 1.342281879  # 400 µm / 298 px
CANVAS_W = 900

st.set_page_config(page_title="Microscope Measurement Tool", layout="wide")
st.title("Microscope Measurement Tool")

if "scale_um_per_px" not in st.session_state:
    st.session_state.scale_um_per_px = load_scale(DEFAULT_SCALE)
if "bg_bytes" not in st.session_state:
    st.session_state.bg_bytes = b""
if "canvas_source_file" not in st.session_state:
    st.session_state.canvas_source_file = ""
if "shapes" not in st.session_state:
    st.session_state.shapes = []
if "label_positions" not in st.session_state:
    st.session_state.label_positions = {}
if "prev_nonlabel_count" not in st.session_state:
    st.session_state.prev_nonlabel_count = 0
if "calibration_mode" not in st.session_state:
    st.session_state.calibration_mode = False

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
    st.session_state.label_positions = {}
    st.session_state.prev_nonlabel_count = 0

if not st.session_state.bg_bytes:
    st.session_state.bg_bytes = uploaded_file.getvalue()

original_image = Image.open(BytesIO(st.session_state.bg_bytes)).convert("RGB")
img_w, img_h = original_image.size

display_w = CANVAS_W
display_h = int(img_h * (display_w / img_w))
scale_x = img_w / display_w
scale_y = img_h / display_h

draw_background = original_image.resize((display_w, display_h), Image.LANCZOS)

st.subheader("Canvas 1: Draw Shapes")
if st.session_state.calibration_mode:
    st.warning("Calibration mode enabled: draw one LINE over the known scale bar.")
    draw_mode = "line"
else:
    draw_mode = "line" if draw_tool == "Line" else "circle"

draw_canvas = st_canvas(
    fill_color="rgba(255, 0, 0, 0.0)",
    stroke_width=2,
    stroke_color="#ff0000",
    background_image=draw_background,
    height=display_h,
    width=display_w,
    drawing_mode=draw_mode,
    initial_drawing={"version": "4.4.0", "objects": st.session_state.shapes},
    update_streamlit=True,
    key="draw_canvas",
)

live_draw_objects = []
if draw_canvas.json_data and "objects" in draw_canvas.json_data:
    live_draw_objects = draw_canvas.json_data["objects"]

# Persist shapes from draw canvas only when new data arrives.
if live_draw_objects != st.session_state.shapes:
    prev_shapes = [o for o in st.session_state.shapes if not o.get("isLabel")]
    incoming_shapes = [o for o in live_draw_objects if not o.get("isLabel")]
    synced_shapes = []
    for idx, shp in enumerate(incoming_shapes):
        new_shape = dict(shp)
        # Keep stable ids if canvas dropped custom fields.
        if not new_shape.get("shapeId") and idx < len(prev_shapes):
            prev_id = prev_shapes[idx].get("shapeId")
            if prev_id:
                new_shape["shapeId"] = prev_id
        if not new_shape.get("labelId") and idx < len(prev_shapes):
            prev_label_id = prev_shapes[idx].get("labelId")
            if prev_label_id:
                new_shape["labelId"] = prev_label_id
        synced_shapes.append(new_shape)
    st.session_state.shapes = synced_shapes

shapes = st.session_state.shapes

nonlabel_count = len(shapes)
prev_count = int(st.session_state.prev_nonlabel_count)
if nonlabel_count > prev_count:
    for shape in shapes:
        shape_id = str(shape.get("shapeId", ""))
        if not shape_id:
            shape_id = str(uuid4())
            shape["shapeId"] = shape_id

        label_id = str(shape.get("labelId", "")).strip()
        if not label_id:
            label_id = f"label_{uuid4()}"
            shape["labelId"] = label_id

        if label_id not in st.session_state.label_positions:
            geom = extract_geometry(shape)
            if not geom:
                continue
            measurement_px = measurement_px_from_geometry(geom, scale_x, scale_y)
            if measurement_px <= 0:
                continue
            measurement_um = measurement_px * st.session_state.scale_um_per_px
            ax, ay = label_anchor_canvas(geom)
            lx, ly = clamp_label_canvas(ax, ay, display_w, display_h, margin=5)
            st.session_state.label_positions[label_id] = {
                "labelId": label_id,
                "forShapeId": shape_id,
                "left": lx,
                "top": ly,
                "text": f"{measurement_um:.2f} µm",
                "fontSize": 50,
                "fill": "rgb(255,0,0)",
                "scaleX": 1.0,
                "scaleY": 1.0,
                "angle": 0.0,
                "width": 200.0,
                "height": 60.0,
            }
        else:
            # Keep text refreshed for measurement updates without moving the label.
            geom = extract_geometry(shape)
            if geom:
                measurement_px = measurement_px_from_geometry(geom, scale_x, scale_y)
                if measurement_px > 0:
                    measurement_um = measurement_px * st.session_state.scale_um_per_px
                    st.session_state.label_positions[label_id]["text"] = f"{measurement_um:.2f} µm"

# Remove labels for deleted shapes.
active_label_ids = {str(s.get("labelId", "")).strip() for s in shapes if s.get("labelId")}
for existing_label_id in list(st.session_state.label_positions.keys()):
    if existing_label_id not in active_label_ids:
        del st.session_state.label_positions[existing_label_id]

st.session_state.prev_nonlabel_count = nonlabel_count

# Measurements from shapes only.
measurements = []
for idx, shape in enumerate(shapes, start=1):
    geom = extract_geometry(shape)
    if not geom:
        continue
    measurement_px = measurement_px_from_geometry(geom, scale_x, scale_y)
    if measurement_px <= 0:
        continue
    measurement_um = measurement_px * st.session_state.scale_um_per_px
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

if not measurements:
    st.info("Draw a shape to see measurements.")
    st.stop()

# Calibration based on latest line.
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

# Build base annotated image (shapes only) in the same resized coordinate space.
base_display = render_base(draw_background, shapes, scale_x=1.0, scale_y=1.0)

label_objects_for_canvas = []
for label_id, item in st.session_state.label_positions.items():
    label_objects_for_canvas.append(
        {
            "type": "textbox",
            "text": str(item.get("text", "")),
            "left": float(item.get("left", 0.0)),
            "top": float(item.get("top", 0.0)),
            "fontSize": float(item.get("fontSize", 50)),
            "fill": str(item.get("fill", "rgb(255,0,0)")),
            "scaleX": float(item.get("scaleX", 1.0)),
            "scaleY": float(item.get("scaleY", 1.0)),
            "angle": float(item.get("angle", 0.0)),
            "width": float(item.get("width", 200.0)),
            "height": float(item.get("height", 60.0)),
            "selectable": True,
            "evented": True,
            "hasControls": True,
            "hasBorders": True,
            "isLabel": True,
            "labelId": str(label_id),
            "forShapeId": str(item.get("forShapeId", "")),
        }
    )

st.subheader("Canvas 2: Drag Labels On Preview")
label_canvas = st_canvas(
    fill_color="rgba(255, 0, 0, 0.0)",
    stroke_width=1,
    stroke_color="#ff0000",
    background_image=base_display,
    height=display_h,
    width=display_w,
    drawing_mode="transform",
    initial_drawing={"version": "4.4.0", "objects": label_objects_for_canvas},
    update_streamlit=True,
    key="label_canvas",
)

if st.button("Apply label positions"):
    if label_canvas.json_data and "objects" in label_canvas.json_data:
        live_label_objects = label_canvas.json_data["objects"]
        for i, obj in enumerate(live_label_objects):
            if not obj.get("isLabel"):
                continue
            label_id = str(obj.get("labelId", "")).strip()
            if not label_id:
                label_id = f"live_label_{i}"
            st.session_state.label_positions[label_id] = {
                "labelId": label_id,
                "forShapeId": str(obj.get("forShapeId", obj.get("labelFor", ""))),
                "left": float(obj.get("left", 0.0)),
                "top": float(obj.get("top", 0.0)),
                "text": str(obj.get("text", "")),
                "fontSize": float(obj.get("fontSize", 50)),
                "fill": str(obj.get("fill", "rgb(255,0,0)")),
                "scaleX": float(obj.get("scaleX", 1.0)),
                "scaleY": float(obj.get("scaleY", 1.0)),
                "angle": float(obj.get("angle", 0.0)),
                "width": float(obj.get("width", 200.0)),
                "height": float(obj.get("height", 60.0)),
            }
        st.success("Label positions applied")

# Final export image = base + labels in the same display coordinate system.
final_full = render_final_with_labels(base_display, label_objects_for_canvas, scale_x=1.0, scale_y=1.0)

png_buf = BytesIO()
final_full.save(png_buf, format="PNG")
st.download_button(
    "Download annotated PNG",
    data=png_buf.getvalue(),
    file_name=f"annotated_{uploaded_file.name.rsplit('.', 1)[0]}.png",
    mime="image/png",
)

st.caption(
    f"Debug: img=({img_w}x{img_h}) | display=({display_w}x{display_h}) | "
    f"scale=({scale_x:.4f},{scale_y:.4f}) | shapes={len(shapes)} labels={len(st.session_state.label_positions)}"
)

table_rows = []
for m in measurements:
    metric = "Length" if m["tool"] == "Line" else "Diameter"
    table_rows.append(
        {
            "#": m["index"],
            "Tool": m["tool"],
            "Metric": metric,
            "Pixels": f"{m['measurement_px']:.2f}",
            "µm": f"{m['measurement_um']:.2f}",
        }
    )

st.dataframe(table_rows, hide_index=True, use_container_width=True)

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
