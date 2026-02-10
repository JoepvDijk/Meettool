from io import StringIO

import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from utils import (
    annotate_image,
    create_annotated_image,
    csv_rows,
    extract_geometry,
    get_annotation_debug_info,
    get_first_circle_debug,
    load_scale,
    save_scale,
)

DEFAULT_SCALE = 1.342281879  # 400 µm / 298 px
MAX_W = 900

st.set_page_config(page_title="Microscope Measurement Tool", layout="wide")
st.title("Microscope Measurement Tool")

if "scale_um_per_px" not in st.session_state:
    st.session_state.scale_um_per_px = load_scale(DEFAULT_SCALE)
if "calibration_mode" not in st.session_state:
    st.session_state.calibration_mode = False

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

image = Image.open(uploaded_file)
img_w, img_h = image.size

display_w = min(img_w, MAX_W)
display_h = int(img_h * (display_w / img_w))
scale_x = img_w / display_w
scale_y = img_h / display_h
canvas_to_img_scale = (scale_x, scale_y)
debug_info = get_annotation_debug_info(img_w)

if st.session_state.calibration_mode:
    st.warning("Calibration mode enabled: draw one LINE over the known scale bar.")
    drawing_mode = "line"
else:
    drawing_mode = "line" if selected_tool == "Line" else "circle"

canvas_result = st_canvas(
    fill_color="rgba(255, 0, 0, 0.0)",
    stroke_width=2,
    stroke_color="#ff0000",
    background_image=image,
    height=display_h,
    width=display_w,
    drawing_mode=drawing_mode,
    key="canvas",
)

objects = []
if canvas_result.json_data and "objects" in canvas_result.json_data:
    objects = canvas_result.json_data["objects"]

if not objects:
    st.info("Draw a shape to see measurements.")
    st.stop()

measurements = []
line_geometries = []

for idx, obj in enumerate(objects, start=1):
    geom = extract_geometry(obj)
    if not geom:
        continue

    # Convert measurement into full-resolution image pixels.
    if geom["type"] == "line":
        x1 = geom["x1"] * scale_x
        y1 = geom["y1"] * scale_y
        x2 = geom["x2"] * scale_x
        y2 = geom["y2"] * scale_y
        measurement_px = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        line_geometries.append({"idx": idx, "measurement_px": measurement_px})
        tool_name = "Line"
    else:
        rx = abs(float(geom.get("rx", geom.get("r", 0.0)))) * scale_x
        ry = abs(float(geom.get("ry", geom.get("r", 0.0)))) * scale_y
        measurement_px = 2.0 * ((rx + ry) / 2.0)
        tool_name = "Circle"

    if measurement_px <= 0:
        continue

    measurement_um = measurement_px * st.session_state.scale_um_per_px
    measurements.append(
        {
            "index": idx,
            "tool": tool_name,
            "measurement_px": measurement_px,
            "measurement_um": measurement_um,
        }
    )

if not measurements:
    st.info("No valid measurable shapes found yet.")
    st.stop()

if st.session_state.calibration_mode:
    if not line_geometries:
        st.info("Calibration mode needs at least one line.")
    else:
        latest_line = line_geometries[-1]
        line_px = latest_line["measurement_px"]
        if line_px <= 0:
            st.error("Invalid calibration: line length must be greater than 0 px.")
        else:
            calibrated_scale = known_length_um / line_px
            st.caption(
                f"Calibration line (latest line #{latest_line['idx']}): {line_px:.2f} px -> {calibrated_scale:.9f} µm/px"
            )
            if st.button("Save scale"):
                st.session_state.scale_um_per_px = calibrated_scale
                save_scale(calibrated_scale)
                st.success("Scale saved to settings.json")
                st.session_state.calibration_mode = False

annotated_image = annotate_image(
    image,
    objects,
    scale_um_per_px=st.session_state.scale_um_per_px,
    canvas_to_img_scale=canvas_to_img_scale,
)
st.image(annotated_image, caption="Annotated preview", width=display_w)
if debug_info["font_is_default"]:
    st.warning("TTF font not found, using default font (will be small).")
st.caption(
    "Debug: "
    f"img=({img_w}x{img_h}) | display=({display_w}x{display_h}) | "
    f"font={debug_info['font_path']} | font_size={debug_info['font_size']}"
)
circle_debug = get_first_circle_debug(objects)
if circle_debug:
    st.caption(
        "Circle debug (first): "
        f"left={circle_debug['left']:.2f}, top={circle_debug['top']:.2f}, "
        f"radius={circle_debug['radius']:.2f}, scaleX={circle_debug['scaleX']:.3f}, "
        f"scaleY={circle_debug['scaleY']:.3f}, cx={circle_debug['cx']:.2f}, "
        f"cy={circle_debug['cy']:.2f}, rx={circle_debug['rx']:.2f}, ry={circle_debug['ry']:.2f}"
    )

st.caption(
    f"Shapes: {len(measurements)} | Scale: {st.session_state.scale_um_per_px:.9f} µm/px"
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

annotated_png = create_annotated_image(
    image,
    objects,
    scale_um_per_px=st.session_state.scale_um_per_px,
    canvas_to_img_scale=canvas_to_img_scale,
)
st.download_button(
    "Download annotated image",
    data=annotated_png,
    file_name=f"annotated_{uploaded_file.name.rsplit('.', 1)[0]}.png",
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
