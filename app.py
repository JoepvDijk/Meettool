from io import BytesIO, StringIO

import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from utils import (
    build_measurements_and_labels,
    csv_rows,
    ensure_shape_ids,
    load_scale,
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
if "shape_counter" not in st.session_state:
    st.session_state.shape_counter = 1
if "objects" not in st.session_state:
    st.session_state.objects = []
if "bg_bytes" not in st.session_state:
    st.session_state.bg_bytes = b""
if "canvas_source_file" not in st.session_state:
    st.session_state.canvas_source_file = ""


uploaded_file = st.file_uploader("Upload image", type=["png", "jpg", "jpeg"])
selected_tool = st.radio("Drawing mode", ["Line", "Circle"], horizontal=True)

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
    drawing_mode = "line" if selected_tool == "Line" else "circle"

font_size = max(60, int(img_w * 0.05))

apply_labels_clicked = st.button("Apply labels")

initial_drawing = {"version": "4.4.0", "objects": st.session_state.objects}
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


shapes, _ = split_shapes_and_labels(objects_live)

measurements, generated_labels, circle_debug = build_measurements_and_labels(
    shapes=shapes,
    scale_um_per_px=st.session_state.scale_um_per_px,
    scale_x=scale_x,
    scale_y=scale_y,
    canvas_w=display_w,
    canvas_h=display_h,
    font_size=font_size,
)

if not measurements:
    st.info("No valid measurable shapes found yet.")
    st.stop()

if apply_labels_clicked and canvas_result.json_data and "objects" in canvas_result.json_data:
    live_objects = canvas_result.json_data["objects"]
    shapes_for_labels, _ = split_shapes_and_labels(live_objects)
    shapes_for_labels, next_counter = ensure_shape_ids(shapes_for_labels, st.session_state.shape_counter)
    st.session_state.shape_counter = next_counter
    _, labels_for_shapes, _ = build_measurements_and_labels(
        shapes=shapes_for_labels,
        scale_um_per_px=st.session_state.scale_um_per_px,
        scale_x=scale_x,
        scale_y=scale_y,
        canvas_w=display_w,
        canvas_h=display_h,
        font_size=50,
    )
    # Save once: base shapes + regenerated labels.
    st.session_state.objects = shapes_for_labels + labels_for_shapes

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
            st.caption(
                f"Calibration line (latest): {line_px:.2f} px -> {calibrated_scale:.9f} µm/px"
            )
            if st.button("Save scale"):
                st.session_state.scale_um_per_px = calibrated_scale
                save_scale(calibrated_scale)
                st.success("Scale saved to settings.json")
                st.session_state.calibration_mode = False

st.caption(
    f"Debug: img=({img_w}x{img_h}) | display=({display_w}x{display_h}) | "
    f"scale=({scale_x:.4f},{scale_y:.4f}) | label_font_size={font_size}"
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
