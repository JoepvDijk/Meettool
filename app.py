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
    make_label_object,
    measurement_px_from_geometry,
    save_scale,
    split_shapes_and_labels,
)

DEFAULT_SCALE = 1.342281879  # 400 µm / 298 px
MAX_W = 900

st.set_page_config(page_title="Microscope Measurement Tool", layout="wide")
st.title("Microscope Measurement Tool")

if "scale_um_per_px" not in st.session_state:
    st.session_state.scale_um_per_px = load_scale(DEFAULT_SCALE)
if "calibration_mode" not in st.session_state:
    st.session_state.calibration_mode = False
if "objects" not in st.session_state:
    st.session_state.objects = []
if "bg_bytes" not in st.session_state:
    st.session_state.bg_bytes = b""
if "canvas_source_file" not in st.session_state:
    st.session_state.canvas_source_file = ""
if "prev_nonlabel_count" not in st.session_state:
    st.session_state.prev_nonlabel_count = 0

uploaded_file = st.file_uploader("Upload image", type=["png", "jpg", "jpeg"])
selected_tool = st.radio("Drawing mode", ["Line", "Circle"], horizontal=True)
mode = st.radio("Mode", ["Draw", "Move labels"], horizontal=True)

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
    st.session_state.objects = []
    st.session_state.prev_nonlabel_count = 0

if not st.session_state.bg_bytes:
    st.session_state.bg_bytes = uploaded_file.getvalue()

image = Image.open(BytesIO(st.session_state.bg_bytes))
img_w, img_h = image.size

display_w = min(img_w, MAX_W)
display_h = int(img_h * (display_w / img_w))
scale_x = img_w / display_w
scale_y = img_h / display_h

if st.session_state.calibration_mode:
    st.warning("Calibration mode enabled: draw one LINE over the known scale bar.")
    drawing_mode = "line"
else:
    if mode == "Move labels":
        drawing_mode = "transform"
    else:
        drawing_mode = "line" if selected_tool == "Line" else "circle"


def _apply_mode_interactivity(objects, mode_name):
    updated = []
    changed = False
    for obj in objects:
        new_obj = dict(obj)
        is_label = bool(new_obj.get("isLabel", False))
        if mode_name == "Move labels":
            if is_label:
                desired = {
                    "selectable": True,
                    "evented": True,
                    "hasControls": True,
                    "hasBorders": True,
                }
            else:
                desired = {
                    "selectable": False,
                    "evented": False,
                    "hasControls": False,
                    "hasBorders": False,
                }
        else:
            desired = {
                "selectable": False,
                "evented": False,
                "hasControls": False,
                "hasBorders": False,
            }

        for k, v in desired.items():
            if new_obj.get(k) != v:
                new_obj[k] = v
                changed = True
        updated.append(new_obj)
    return updated, changed


objects_for_canvas, mode_flags_changed = _apply_mode_interactivity(st.session_state.objects, mode)
if mode_flags_changed:
    st.session_state.objects = objects_for_canvas

initial_drawing = {"version": "4.4.0", "objects": objects_for_canvas}
canvas_result = st_canvas(
    fill_color="rgba(255, 0, 0, 0.0)",
    stroke_width=2,
    stroke_color="#ff0000",
    background_image=image,
    height=display_h,
    width=display_w,
    drawing_mode=drawing_mode,
    initial_drawing=initial_drawing,
    update_streamlit=True,
    key="measure_canvas",
)

objects_live = st.session_state.objects
if canvas_result.json_data and "objects" in canvas_result.json_data:
    objects_live = canvas_result.json_data["objects"]

if not objects_live:
    st.info("Draw a shape to see measurements.")
    st.stop()

live_shapes, live_labels = split_shapes_and_labels(objects_live)
nonlabel_count = len(live_shapes)
if "prev_nonlabel_count" not in st.session_state:
    st.session_state.prev_nonlabel_count = 0
prev_nonlabel_count = int(st.session_state.prev_nonlabel_count)
label_for_ids = {
    str(lbl.get("labelFor", ""))
    for lbl in live_labels
    if lbl.get("isLabel") and lbl.get("labelFor")
}

mutated = False
new_labels = []
if nonlabel_count > prev_nonlabel_count:
    for shape in live_shapes:
        shape_id = str(shape.get("shapeId", ""))
        if not shape_id:
            shape_id = str(uuid4())
            shape["shapeId"] = shape_id
            mutated = True

        if shape_id not in label_for_ids:
            geom = extract_geometry(shape)
            if not geom:
                continue
            measurement_px = measurement_px_from_geometry(geom, scale_x, scale_y)
            if measurement_px <= 0:
                continue
            measurement_um = measurement_px * st.session_state.scale_um_per_px
            ax, ay = label_anchor_canvas(geom)
            lx, ly = clamp_label_canvas(ax, ay, display_w, display_h, margin=5)
            new_labels.append(
                make_label_object(
                    shape_id=shape_id,
                    text=f"{measurement_um:.2f} µm",
                    x=lx,
                    y=ly,
                    font_size=50,
                )
            )
            label_for_ids.add(shape_id)
            mutated = True

if new_labels:
    live_labels = live_labels + new_labels

if mutated:
    updated_objects = live_shapes + live_labels
    updated_objects, _ = _apply_mode_interactivity(updated_objects, mode)
    if updated_objects != st.session_state.objects:
        st.session_state.objects = updated_objects

st.session_state.prev_nonlabel_count = nonlabel_count

measurements = []
circle_debug = []
for idx, shape in enumerate(live_shapes, start=1):
    if shape.get("isLabel"):
        continue
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

st.caption(
    f"Debug: img=({img_w}x{img_h}) | display=({display_w}x{display_h}) | "
    f"scale=({scale_x:.4f},{scale_y:.4f})"
)
if circle_debug:
    d = circle_debug[0]
    st.caption(
        "Circle debug (first): "
        f"left={d['left']:.2f}, top={d['top']:.2f}, radius={d['radius']:.2f}, "
        f"scaleX={d['scaleX']:.3f}, scaleY={d['scaleY']:.3f}, "
        f"cx={d['cx']:.2f}, cy={d['cy']:.2f}, rx={d['rx']:.2f}, ry={d['ry']:.2f}"
    )

st.caption(f"Shapes: {len(measurements)} | Scale: {st.session_state.scale_um_per_px:.9f} µm/px")

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

if canvas_result.image_data is not None:
    overlay = Image.fromarray(canvas_result.image_data.astype("uint8"), mode="RGBA")
    background = image.convert("RGBA").resize((display_w, display_h), Image.LANCZOS)
    out_image = Image.alpha_composite(background, overlay)
    out_buffer = BytesIO()
    out_image.save(out_buffer, format="PNG")
    st.download_button(
        "Download canvas image",
        data=out_buffer.getvalue(),
        file_name=f"canvas_{uploaded_file.name.rsplit('.', 1)[0]}.png",
        mime="image/png",
    )

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
