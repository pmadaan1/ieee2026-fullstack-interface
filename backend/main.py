import asyncio
import json
import os
import time
from collections import deque

import joblib
import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import firebase_store
from analysis.analyze import analyze_window
from analysis.activity_analysis import predict_buffer as predict_activity_pd

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
LEGACY_MODEL_PATH = os.path.join(ANALYSIS_DIR, "models", "lgbm_model_typeClass")
if not os.path.exists(LEGACY_MODEL_PATH):
    # Older layout — fall back to the original location.
    LEGACY_MODEL_PATH = os.path.join(ANALYSIS_DIR, "lgbm_model_typeClass")
MODEL = joblib.load(LEGACY_MODEL_PATH)
with open(os.path.join(ANALYSIS_DIR, "model_metadata.json")) as f:
    METADATA = json.load(f)

FS = METADATA.get("sampling_rate_hz", 50)
WINDOW_S = 10
BUFFER_LEN = FS * WINDOW_S        # 500 samples @ 50 Hz
ANALYZE_EVERY_S = 0.5             # slide the 10s analysis window every 0.5 s

# Long-term storage: aggregate ~120 ticks (one minute @ 0.5 s cadence) into a
# single Firestore doc. Set FIREBASE_USER_ID to override the default uid.
MINUTE_MS = 60_000
DEFAULT_UID = os.environ.get("FIREBASE_USER_ID", "demo-user")
firebase_store.init()

# The LightGBM classifier was trained on raw MPU6050 int16 counts (±2 g
# accel = 16384 raw/g; ±250 °/s gyro = 131 raw/dps). The browser sends
# physical units, so we scale up before handing the window to the model
# and pass is_si=False — the foot-clearance estimator then divides back
# down internally and everything downstream sees the units it expects.
ACCEL_RAW_PER_MS2 = 16384.0 / 9.81   # ≈ 1670.34
GYRO_RAW_PER_DPS  = 131.0

# Idle gate: when intensity is below this, the step detector fires on
# noise (its threshold is std-relative). Force every motion metric to 0.
IDLE_INTENSITY_THRESHOLD = 0.3       # m/s²

# Physical sanity caps — guard against integration drift in the foot
# clearance estimator producing impossible values.
MAX_CLEARANCE_CM = 30.0
MAX_STRIDE_M     = 1.6
MAX_SPEED_MPS    = 2.5


def _buffer_to_df(buffer) -> pd.DataFrame:
    """Build a DataFrame in raw int16 counts (model's training scale)."""
    return pd.DataFrame([{
        "timestamp":   r["esp32_ms"],
        "accel_x":     r["ax"] * ACCEL_RAW_PER_MS2,
        "accel_y":     r["ay"] * ACCEL_RAW_PER_MS2,
        "accel_z":     r["az"] * ACCEL_RAW_PER_MS2,
        "gyro_x":      r["gx"] * GYRO_RAW_PER_DPS,
        "gyro_y":      r["gy"] * GYRO_RAW_PER_DPS,
        "gyro_z":      r["gz"] * GYRO_RAW_PER_DPS,
        "temperature": 25.0,
    } for r in buffer])


def _phase_durations(stance_mask, fs):
    """Mean stance and swing duration (seconds) from a 0/1 stance mask."""
    if not stance_mask:
        return 0.0, 0.0
    stance_runs, swing_runs = [], []
    cur_val = stance_mask[0]
    cur_len = 1
    for v in stance_mask[1:]:
        if v == cur_val:
            cur_len += 1
        else:
            (stance_runs if cur_val == 1 else swing_runs).append(cur_len)
            cur_val, cur_len = v, 1
    (stance_runs if cur_val == 1 else swing_runs).append(cur_len)
    stance_t = (sum(stance_runs) / len(stance_runs)) / fs if stance_runs else 0.0
    swing_t  = (sum(swing_runs)  / len(swing_runs))  / fs if swing_runs  else 0.0
    return stance_t, swing_t


def _idle_metrics(intensity_value: float, jerk_value: float) -> dict:
    return {
        "classification":   "Stationary",
        "confidence":       None,
        "state":            "idle",
        "state_confidence": 100,
        "cadence":          0.0,
        "steps":            0,
        "clearance":        0.0,
        "clearance_min":    0.0,
        "clearance_max":    0.0,
        "similarity":       None,
        "speed":            0.0,
        "stride":           0.0,
        "intensity":        round(intensity_value, 2),
        "jerk":             round(jerk_value, 1),
        "stance_pct":       100.0,
        "asymmetry":        None,
        "variability":      None,
        "step_time":        None,
        "stance_time":      None,
        "swing_time":       None,
        # Activity model output is overridden during true idle so the UI
        # doesn't display "Walking" while the device is at rest.
        "activity":              "Idle",
        "activity_confidence":   100,
        "activity_distribution": {},
        "parkinsons":            None,
        "parkinsons_confidence": None,
    }


def _flatten_metrics(insights: dict, activity_pred: dict | None = None) -> dict:
    m = insights["metrics"]
    s = insights["state"]
    sig = insights.get("signals", {})
    intensity = float(m["movement_intensity_mps2"])
    sim = m["gait_similarity_score"]
    diag = m.get("gait_similarity_diagnostics") or {}

    # Idle gate (see comments above for rationale).
    if intensity < IDLE_INTENSITY_THRESHOLD or s["predicted_state"] == "idle":
        return _idle_metrics(intensity, float(m["jerk_rms_mps3"]))

    # Physical sanity caps — guard against integrator drift in clearance.
    clearance     = min(float(m["foot_clearance_mean_cm"]), MAX_CLEARANCE_CM)
    clearance_min = min(float(m["foot_clearance_min_cm"]),  MAX_CLEARANCE_CM)
    clearance_max = min(float(m["foot_clearance_max_cm"]),  MAX_CLEARANCE_CM)
    stride        = min(float(m["stride_length_m_est"]),    MAX_STRIDE_M)
    speed         = min(float(m["walking_speed_mps_est"]),  MAX_SPEED_MPS)

    # Derived rhythm metrics from gait_similarity diagnostics (only present
    # when ≥4 steps were detected — otherwise we report None).
    asymmetry  = round(float(diag["asymmetry"]) * 100, 1) if "asymmetry" in diag else None
    variability = round(float(diag["cv"]) * 100, 1)        if "cv" in diag        else None
    step_time  = round(float(diag["mean_interval_s"]), 2)  if "mean_interval_s" in diag else None

    # Stance / swing durations from the per-sample stance mask.
    stance_t, swing_t = _phase_durations(sig.get("stance_mask", []), FS)

    out = {
        "classification":   m["gait_classification"],
        "confidence":       round(float(m["gait_classification_confidence"]) * 100),
        "state":            s["predicted_state"],
        "state_confidence": round(float(s["confidence"]) * 100),
        "cadence":          round(float(m["cadence_spm"]), 1),
        "steps":            int(m["step_count"]),
        "clearance":        round(clearance, 1),
        "clearance_min":    round(clearance_min, 1),
        "clearance_max":    round(clearance_max, 1),
        "similarity":       None if sim is None else round(float(sim), 1),
        "speed":            round(speed, 2),
        "stride":           round(stride, 2),
        "intensity":        round(intensity, 2),
        "jerk":             round(float(m["jerk_rms_mps3"]), 1),
        "stance_pct":       round(float(m["stance_phase_fraction"]) * 100, 1),
        "asymmetry":        asymmetry,
        "variability":      variability,
        "step_time":        step_time,
        "stance_time":      round(stance_t, 2) if stance_t else None,
        "swing_time":       round(swing_t, 2)  if swing_t  else None,
    }
    # Merge new activity / Parkinson's predictions when available.
    if activity_pred:
        out.update({
            "activity":              activity_pred.get("activity"),
            "activity_confidence":   activity_pred.get("activity_confidence"),
            "activity_distribution": activity_pred.get("activity_distribution", {}),
            "parkinsons":            activity_pred.get("parkinsons"),
            "parkinsons_confidence": activity_pred.get("parkinsons_confidence"),
        })
    else:
        out.update({
            "activity":              None,
            "activity_confidence":   None,
            "activity_distribution": {},
            "parkinsons":            None,
            "parkinsons_confidence": None,
        })
    return out


def _compute_metrics(buffer_rows: list[dict]) -> dict:
    """Run the legacy gait analysis + new activity/PD models on one buffer.

    Both calls are CPU-bound; running them sequentially in a single
    asyncio.to_thread keeps overhead low and avoids two round-trips.
    """
    df = _buffer_to_df(buffer_rows)
    insights = analyze_window(df, FS, MODEL, METADATA, False)  # is_si=False (raw counts)
    activity_pred = predict_activity_pd(buffer_rows)
    return _flatten_metrics(insights, activity_pred=activity_pred)


def _flush_minute(uid: str, current_minute_ms: int, samples: list[dict]) -> None:
    """Synchronous wrapper for the Firestore write — called via to_thread.

    Skips minutes with only idle samples (don't pollute long-term storage
    with sit-still data — gait metrics there are all zero anyway).
    """
    active = [s for s in samples if s.get("state") not in (None, "idle")]
    if not active:
        return
    firebase_store.write_minute(uid, current_minute_ms, active)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Per-connection rolling buffer + analysis throttle.
    buffer: deque = deque(maxlen=BUFFER_LEN)
    last_analyzed = 0.0

    # Long-term aggregator state (flush at each minute boundary).
    minute_samples: list[dict] = []
    current_minute_ms: int | None = None

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
                try:
                    metrics = await asyncio.to_thread(_compute_metrics, list(buffer))
                    await websocket.send_text(json.dumps({"metrics": metrics}))

                    # Bucket into the current minute and flush at boundaries.
                    minute_ms = int((now * 1000) // MINUTE_MS) * MINUTE_MS
                    if current_minute_ms is None:
                        current_minute_ms = minute_ms
                    if minute_ms != current_minute_ms:
                        # Minute rolled over — flush the previous minute, then start fresh.
                        to_flush = minute_samples[:]
                        flush_ts = current_minute_ms
                        minute_samples = []
                        current_minute_ms = minute_ms
                        asyncio.create_task(asyncio.to_thread(
                            _flush_minute, DEFAULT_UID, flush_ts, to_flush
                        ))
                    minute_samples.append(metrics)
                except Exception as e:
                    print(f"analysis error: {e}")
    except WebSocketDisconnect:
        pass
    finally:
        # On disconnect, flush whatever we have so the trailing minute isn't lost.
        if current_minute_ms is not None and minute_samples:
            await asyncio.to_thread(
                _flush_minute, DEFAULT_UID, current_minute_ms, minute_samples
            )
