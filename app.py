from io import StringIO

import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from utils import (
    create_annotated_image,
    csv_row,
    label_position_from_object,
    load_scale,
    measurement_from_canvas_object,
    save_scale,
)

DEFAULT_SCALE = 1.342281879  # 400 µm / 298 px

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
    height=img_h,
    width=img_w,
    drawing_mode=drawing_mode,
    key="canvas",
)

objects = []
if canvas_result.json_data and "objects" in canvas_result.json_data:
    objects = canvas_result.json_data["objects"]

if not objects:
    st.info("Draw a shape to see measurements.")
    st.stop()

latest_obj = objects[-1]
active_tool = "Line" if st.session_state.calibration_mode else selected_tool
measurement_px = measurement_from_canvas_object(latest_obj, active_tool)

if measurement_px <= 0:
    st.error("Invalid shape measurement (0 px). Please draw again.")
    st.stop()

if st.session_state.calibration_mode:
    calibrated_scale = known_length_um / measurement_px
    st.write(f"Calibration line length: **{measurement_px:.2f} px**")
    st.write(f"Computed scale: **{calibrated_scale:.9f} µm/px**")

    if st.button("Save scale"):
        if measurement_px <= 0:
            st.error("Invalid calibration: line length must be greater than 0 px.")
        else:
            st.session_state.scale_um_per_px = calibrated_scale
            save_scale(calibrated_scale)
            st.session_state.calibration_mode = False
            st.success("Scale saved to settings.json")
    st.stop()

measurement_um = measurement_px * st.session_state.scale_um_per_px
metric_name = "Length" if selected_tool == "Line" else "Diameter"

st.subheader("Measurement")
st.write(f"{metric_name} (px): **{measurement_px:.2f}**")
st.write(f"{metric_name} (µm): **{measurement_um:.2f}**")

label_text = f"{metric_name}: {measurement_um:.2f} µm"
label_x, label_y = label_position_from_object(latest_obj, selected_tool)
st.caption(f"Overlay label position: x={label_x:.1f}, y={label_y:.1f} | {label_text}")

annotated_png = create_annotated_image(image, latest_obj, selected_tool, label_text)
st.download_button(
    "Download annotated image",
    data=annotated_png,
    file_name=f"annotated_{uploaded_file.name.rsplit('.', 1)[0]}.png",
    mime="image/png",
)

csv_data = csv_row(
    filename=uploaded_file.name,
    tool=selected_tool,
    measurement_px=measurement_px,
    measurement_um=measurement_um,
    scale_um_per_px=st.session_state.scale_um_per_px,
)

st.download_button(
    "Download measurements CSV",
    data=StringIO(csv_data).getvalue(),
    file_name="measurement.csv",
    mime="text/csv",
)
