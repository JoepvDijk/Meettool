# Microscope Measurement Tool

A minimal local Streamlit app for microscope image measurement.

## Features
- Upload PNG/JPG microscope images
- Draw one line or circle on top of the image
- Line mode: reports length in px and µm
- Circle mode: reports diameter in px and µm
- Constant scale input (µm per pixel)
- Optional calibration mode from a known scale bar line
- Save/load calibration scale from `settings.json`
- Download annotated PNG with shape + label
- Download CSV measurement export

## Project structure
- `app.py`: main Streamlit UI
- `utils.py`: measurement, calibration persistence, annotation, CSV helpers
- `requirements.txt`: Python dependencies
- `README.md`: setup and run instructions

## macOS setup and run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL shown by Streamlit (typically `http://localhost:8501`).

## Calibration workflow
1. Click **Enter calibration mode** in the sidebar.
2. Draw a line over a known scale bar in the image.
3. Set **Known length (µm)** (default `400`).
4. Click **Save scale** to persist computed `µm/px` to `settings.json`.

## Notes
- If multiple shapes are present, the latest one is used.
- Circle measurement is diameter (`2 * radius`) in pixels, then converted to µm.
- The app validates missing image, missing drawing, and zero-length calibration lines.
