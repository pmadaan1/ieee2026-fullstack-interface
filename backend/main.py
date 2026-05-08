import asyncio
import json
import os
import time
from collections import deque

import joblib
import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from analysis.analyze import analyze_window

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- analysis config -------------------------------------------------------

ANALYSIS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis")
MODEL = joblib.load(os.path.join(ANALYSIS_DIR, "lgbm_model_typeClass"))
with open(os.path.join(ANALYSIS_DIR, "model_metadata.json")) as f:
    METADATA = json.load(f)

FS = METADATA.get("sampling_rate_hz", 50)
WINDOW_S = 10
BUFFER_LEN = FS * WINDOW_S        # 500 samples @ 50 Hz
ANALYZE_EVERY_S = 1.0              # slide the analysis window every 1 s


def _buffer_to_df(buffer) -> pd.DataFrame:
    """Build a DataFrame matching analyze.RAW_COLS in physical units (m/s², °/s)."""
    return pd.DataFrame([{
        "timestamp":   r["esp32_ms"],
        "accel_x":     r["ax"], "accel_y": r["ay"], "accel_z": r["az"],
        "gyro_x":      r["gx"], "gyro_y":  r["gy"], "gyro_z":  r["gz"],
        "temperature": 25.0,
    } for r in buffer])


def _flatten_metrics(insights: dict) -> dict:
    m = insights["metrics"]
    s = insights["state"]
    sim = m["gait_similarity_score"]
    return {
        # gait classification (from rule-based classify_gait)
        "classification":      m["gait_classification"],
        "confidence":          round(float(m["gait_classification_confidence"]) * 100),
        # activity state (from LightGBM model)
        "state":               s["predicted_state"],
        "state_confidence":    round(float(s["confidence"]) * 100),
        # core gait metrics
        "cadence":             round(float(m["cadence_spm"]), 1),
        "steps":               int(m["step_count"]),
        "clearance":           round(float(m["foot_clearance_mean_cm"]), 1),
        "clearance_min":       round(float(m["foot_clearance_min_cm"]), 1),
        "clearance_max":       round(float(m["foot_clearance_max_cm"]), 1),
        "similarity":          None if sim is None else round(float(sim), 1),
        # additional kinematics
        "speed":               round(float(m["walking_speed_mps_est"]), 2),
        "stride":              round(float(m["stride_length_m_est"]), 2),
        "intensity":           round(float(m["movement_intensity_mps2"]), 2),
        "jerk":                round(float(m["jerk_rms_mps3"]), 1),
        "stance_pct":          round(float(m["stance_phase_fraction"]) * 100, 1),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Per-connection rolling buffer + analysis throttle.
    buffer: deque = deque(maxlen=BUFFER_LEN)
    last_analyzed = 0.0

    try:
        while True:
            data = await websocket.receive_json()       # raw IMU frame from browser
            raw = data.get("raw")
            if not raw:
                continue
            buffer.append(raw)

            now = time.time()
            if len(buffer) == BUFFER_LEN and (now - last_analyzed) >= ANALYZE_EVERY_S:
                last_analyzed = now
                df = _buffer_to_df(buffer)
                try:
                    insights = await asyncio.to_thread(
                        analyze_window, df, FS, MODEL, METADATA, True  # is_si=True
                    )
                    metrics = _flatten_metrics(insights)
                    await websocket.send_text(json.dumps({"metrics": metrics}))
                except Exception as e:
                    print(f"analysis error: {e}")
    except WebSocketDisconnect:
        pass
