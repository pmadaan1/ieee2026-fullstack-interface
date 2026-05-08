"""Extract gait insights from a 10-second IMU window.

Reads raw MPU6050 IMU data from the data/ folder, runs the trained LightGBM
model to predict the user's activity state, and computes per-window gait
metrics (cadence, step count, foot clearance, gait similarity, etc.).
Output is a single JSON record suitable for forwarding to a database that
will accumulate results over time.

The feature-extraction, step-detection, foot-clearance, and gait-similarity
helpers are lifted directly from steadystepmodel.py so the analysis pipeline
matches what the model was trained on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore", message=".*InconsistentVersionWarning.*")
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

import joblib
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, find_peaks


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(HERE, "lgbm_model_typeClass")
DEFAULT_METADATA = os.path.join(HERE, "model_metadata.json")
DEFAULT_DATA_DIR = os.path.join(HERE, "data")

RAW_COLS = ["timestamp", "accel_x", "accel_y", "accel_z",
            "gyro_x", "gyro_y", "gyro_z", "temperature"]

# MPU6050 raw counts → physical units. Training data is raw int16 from a
# ±2 g accel range and ±250 °/s gyro range, which is what these constants
# convert from.
ACCEL_RAW_PER_G = 16384.0
GYRO_RAW_PER_DPS = 131.0
G_MS2 = 9.81


# -- feature extraction (matches steadystepmodel.py) ------------------------

def add_magnitude(data: pd.DataFrame, magnitude_groups: dict) -> pd.DataFrame:
    data = data.copy()
    for new_col, axes in magnitude_groups.items():
        data[new_col] = np.sqrt(np.sum(data[axes].values ** 2, axis=1))
    return data


def raw_to_windows(data: pd.DataFrame, window_size: int, step: int,
                   sample_rate: int,
                   freq_bands=((0.5, 3.0), (3.0, 6.0))) -> pd.DataFrame:
    rows = []
    cols = list(data.columns)
    freqs = np.fft.rfftfreq(window_size, d=1.0 / sample_rate)

    for start in range(0, len(data) - window_size + 1, step):
        window = data.iloc[start:start + window_size]
        feats = {"window_start": start}
        for col in cols:
            x = window[col].values
            feats[f"{col}_mean"] = x.mean()
            feats[f"{col}_std"] = x.std()
            feats[f"{col}_min"] = x.min()
            feats[f"{col}_max"] = x.max()
            feats[f"{col}_range"] = x.max() - x.min()
            feats[f"{col}_rms"] = np.sqrt(np.mean(x ** 2))
            spec = np.abs(np.fft.rfft(x - x.mean()))
            dom_bin = 1 + np.argmax(spec[1:]) if len(spec) > 1 else 0
            feats[f"{col}_dom_freq"] = freqs[dom_bin]
            for low, high in freq_bands:
                mask = (freqs >= low) & (freqs < high)
                feats[f"{col}_energy_{low}-{high}Hz"] = np.sum(spec[mask] ** 2)
        rows.append(feats)
    return pd.DataFrame(rows)


def extract_features(dataset: pd.DataFrame, window_size=100, step=50,
                     sample_rate=50) -> pd.DataFrame:
    data = add_magnitude(dataset, {
        "accel_mag": ["accel_x", "accel_y", "accel_z"],
        "gyro_mag": ["gyro_x", "gyro_y", "gyro_z"],
    })
    return raw_to_windows(data, window_size, step, sample_rate)


# -- step detection ---------------------------------------------------------

def detect_steps(data: pd.DataFrame, fs: int = 50):
    mag = np.sqrt(data["accel_x"] ** 2 + data["accel_y"] ** 2 + data["accel_z"] ** 2)
    low_hz, high_hz = 0.5, 3.0
    nyq = fs / 2.0
    if high_hz >= nyq:
        high_hz = nyq * 0.95
    if low_hz >= high_hz:
        low_hz = max(0.05, high_hz * 0.1)
    b, a = butter(4, [low_hz, high_hz], btype="band", fs=fs)
    mag_filt = filtfilt(b, a, mag - mag.mean())
    threshold = mag_filt.std() * 1.0
    peaks, _ = find_peaks(
        mag_filt,
        height=threshold,
        distance=max(1, int(0.3 * fs)),
        prominence=threshold * 0.5,
    )
    return peaks, mag_filt


# -- foot clearance ---------------------------------------------------------

def detect_stance_phases(data: pd.DataFrame, fs: int = 50,
                         accel_var_thresh=None, gyro_mag_thresh=None):
    gyro_mag = np.sqrt(data["gyro_x"] ** 2 + data["gyro_y"] ** 2 + data["gyro_z"] ** 2)
    accel_mag = np.sqrt(data["accel_x"] ** 2 + data["accel_y"] ** 2 + data["accel_z"] ** 2)
    win = max(int(0.05 * fs), 3)
    accel_var = pd.Series(accel_mag).rolling(win, center=True).var().fillna(0).values
    if gyro_mag_thresh is None:
        gyro_mag_thresh = np.percentile(gyro_mag, 30)
    if accel_var_thresh is None:
        accel_var_thresh = np.percentile(accel_var, 30)
    return (gyro_mag < gyro_mag_thresh) & (accel_var < accel_var_thresh)


def estimate_foot_clearance(data: pd.DataFrame, fs: int = 50,
                            gravity_raw: float = ACCEL_RAW_PER_G,
                            assume_si: bool = False):
    if assume_si:
        ax = data["accel_x"].values
        ay = data["accel_y"].values
        az = data["accel_z"].values
    else:
        ax = data["accel_x"].values / gravity_raw * G_MS2
        ay = data["accel_y"].values / gravity_raw * G_MS2
        az = data["accel_z"].values / gravity_raw * G_MS2

    a_mag = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    a_vert = a_mag - G_MS2

    stance = detect_stance_phases(data, fs=fs)
    dt = 1.0 / fs
    velocity = np.zeros(len(a_vert))
    position = np.zeros(len(a_vert))

    clearances = []
    in_swing = False
    swing_start = 0

    for i in range(1, len(a_vert)):
        if stance[i]:
            if in_swing:
                swing_height = position[swing_start:i].max() - position[swing_start]
                clearances.append(swing_height)
                in_swing = False
            velocity[i] = 0.0
            position[i] = position[i - 1]
        else:
            if not in_swing:
                in_swing = True
                swing_start = i
                position[i] = position[i - 1]
            velocity[i] = velocity[i - 1] + a_vert[i] * dt
            position[i] = position[i - 1] + velocity[i] * dt

    return np.array(clearances), stance


# -- gait similarity / classification --------------------------------------

def gait_similarity(peaks: np.ndarray, fs: int = 50):
    if len(peaks) < 4:
        return None, {"reason": "fewer than 4 steps"}

    intervals = np.diff(peaks) / fs
    cv = intervals.std() / intervals.mean()

    odd_intervals = intervals[::2]
    even_intervals = intervals[1::2]
    n = min(len(odd_intervals), len(even_intervals))
    if n >= 2:
        asymmetry = abs(odd_intervals[:n].mean() - even_intervals[:n].mean()) / intervals.mean()
    else:
        asymmetry = 0.0

    cv_score = np.clip(1 - (cv - 0.03) / 0.17, 0, 1)
    asym_score = np.clip(1 - (asymmetry - 0.02) / 0.18, 0, 1)
    combined = 0.45 * cv_score + 0.55 * asym_score
    score_1_to_10 = 1 + 9 * combined

    return float(score_1_to_10), {
        "cv": float(cv),
        "asymmetry": float(asymmetry),
        "mean_interval_s": float(intervals.mean()),
        "n_steps": int(len(peaks)),
    }


def classify_gait(cadence: float, mean_clearance_cm: float,
                  asymmetry: float, cv: float):
    if asymmetry > 0.15:
        return "Limping", min(asymmetry / 0.30, 1.0)
    if mean_clearance_cm < 5 and cadence > 110:
        return "Shuffling", min((10 - mean_clearance_cm) / 10, 1.0)
    if cv > 0.12:
        return "Unsteady", min(cv / 0.20, 1.0)
    return "Normal", 1.0 - max(cv / 0.10, asymmetry / 0.10, 0)


# -- additional metrics -----------------------------------------------------

def estimate_stride_length_m(mean_clearance_m: float) -> float:
    """Rough Zijlstra-style stride length from peak swing height.

    stride_length ≈ 2 * sqrt(2 * L * h) for a leg of length L and vertical
    foot displacement h. Using L ≈ 0.85 m (average adult leg length).
    """
    if mean_clearance_m <= 0:
        return 0.0
    return float(2 * np.sqrt(2 * 0.85 * max(mean_clearance_m, 1e-4)))


def detect_sit_stand_transitions(data: pd.DataFrame, fs: int = 50) -> int:
    """Count likely sit↔stand transitions inside the window.

    A sit/stand on a foot-mounted IMU shows up as a brief, isolated burst of
    accel after a long quiet stretch (no step rhythm). We approximate this by
    counting accel-magnitude excursions ≥ 1.5σ that are not bracketed by other
    excursions within ±1 s.
    """
    accel_mag = np.sqrt(data["accel_x"] ** 2 + data["accel_y"] ** 2 + data["accel_z"] ** 2)
    z = (accel_mag - accel_mag.mean()) / (accel_mag.std() + 1e-9)
    bursts, _ = find_peaks(z, height=1.5, distance=int(1.0 * fs))
    isolated = 0
    for i, p in enumerate(bursts):
        prev_gap = (p - bursts[i - 1]) / fs if i > 0 else 99
        next_gap = (bursts[i + 1] - p) / fs if i < len(bursts) - 1 else 99
        if prev_gap > 1.0 and next_gap > 1.0:
            isolated += 1
    return isolated


def movement_intensity(data: pd.DataFrame, assume_si: bool = False) -> float:
    """RMS of detrended accel magnitude in m/s² — overall agitation level."""
    mag = np.sqrt(data["accel_x"] ** 2 + data["accel_y"] ** 2 + data["accel_z"] ** 2)
    detrended = mag - mag.mean()
    rms = float(np.sqrt(np.mean(detrended ** 2)))
    if assume_si:
        return rms
    return rms / ACCEL_RAW_PER_G * G_MS2


def jerk_rms(data: pd.DataFrame, fs: int = 50, assume_si: bool = False) -> float:
    """RMS of accel derivative (m/s³). High jerk = jerky, less-controlled motion."""
    a_mag = np.sqrt(data["accel_x"] ** 2 + data["accel_y"] ** 2 + data["accel_z"] ** 2).values
    a_mag_si = a_mag if assume_si else a_mag / ACCEL_RAW_PER_G * G_MS2
    jerk = np.diff(a_mag_si) * fs
    return float(np.sqrt(np.mean(jerk ** 2)))


# -- main analysis pipeline ------------------------------------------------

CANONICAL_COL_MAP = {
    "esp32_ms": "timestamp",
    "ax": "accel_x", "ay": "accel_y", "az": "accel_z",
    "gx": "gyro_x", "gy": "gyro_y", "gz": "gyro_z",
}


def load_data(csv_path: str, has_header: bool):
    """Load IMU CSV in either format. Returns (df, fs_hz, is_si).

    Canonical format (header present): mac_timestamp, esp32_ms, ax, ay, az, gx, gy, gz
        - values are physical units (m/s², rad/s); is_si=True
        - fs is inferred from esp32_ms deltas
    Training format (no header): timestamp, accel_x, ..., gyro_z, temperature
        - values are raw int16 counts; is_si=False
        - fs falls back to the model metadata's sampling_rate_hz
    """
    if has_header:
        df = pd.read_csv(csv_path)
    else:
        df = pd.read_csv(csv_path, header=None, names=RAW_COLS)

    # Detect canonical format and rename to model's column scheme.
    if "esp32_ms" in df.columns:
        df = df.rename(columns=CANONICAL_COL_MAP)
        is_si = True
    elif "ax" in df.columns and "accel_x" not in df.columns:
        df = df.rename(columns=CANONICAL_COL_MAP)
        is_si = True
    else:
        is_si = False

    missing = [c for c in ["accel_x", "accel_y", "accel_z",
                           "gyro_x", "gyro_y", "gyro_z"] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in {csv_path}: {missing}")

    if "timestamp" not in df.columns:
        df.insert(0, "timestamp", np.arange(len(df)) * 20)
    if "temperature" not in df.columns:
        df["temperature"] = 25.0

    ts = df["timestamp"].values
    dt_ms = float(np.median(np.diff(ts))) if len(ts) > 1 else 20.0
    fs = int(round(1000.0 / dt_ms)) if dt_ms > 0 else 50

    return df[RAW_COLS].reset_index(drop=True), fs, is_si


def slice_window(df: pd.DataFrame, fs: int, seconds: float, offset_s: float) -> pd.DataFrame:
    n = int(seconds * fs)
    start = int(offset_s * fs)
    end = start + n
    if end > len(df):
        raise ValueError(f"Requested {seconds}s starting at {offset_s}s but file only has {len(df)/fs:.1f}s")
    return df.iloc[start:end].reset_index(drop=True)


def predict_state(model, metadata: dict, window: pd.DataFrame, fs: int):
    feature_cols = metadata["feature_columns"]
    win_size = metadata.get("window_size", 100)
    overlap = metadata.get("overlap", 50)

    feats = extract_features(window, window_size=win_size, step=overlap,
                             sample_rate=fs)
    if len(feats) == 0:
        raise ValueError("Not enough samples to form even one feature window.")

    X = feats.reindex(columns=feature_cols, fill_value=0.0)
    proba = model.predict_proba(X)
    classes = list(model.classes_)

    mean_proba = proba.mean(axis=0)
    top_idx = int(np.argmax(mean_proba))
    per_window_class = [classes[i] for i in proba.argmax(axis=1)]

    return {
        "predicted_state": classes[top_idx],
        "confidence": float(mean_proba[top_idx]),
        "class_probabilities": {c: float(p) for c, p in zip(classes, mean_proba)},
        "per_window_predictions": [
            {"window_start_sample": int(feats["window_start"].iloc[i]),
             "predicted": per_window_class[i],
             "probabilities": {c: float(p) for c, p in zip(classes, proba[i])}}
            for i in range(len(feats))
        ],
    }


def analyze_window(window: pd.DataFrame, fs: int, model, metadata: dict,
                   is_si: bool = False) -> dict:
    duration_s = len(window) / fs
    state = predict_state(model, metadata, window, fs)

    peaks, mag_filt = detect_steps(window, fs=fs)
    step_count = int(len(peaks))
    cadence_spm = step_count / (duration_s / 60.0) if duration_s > 0 else 0.0

    clearances, stance_mask = estimate_foot_clearance(window, fs=fs, assume_si=is_si)
    if len(clearances) > 0:
        mean_clear_m = float(np.mean(clearances))
        max_clear_m = float(np.max(clearances))
        min_clear_m = float(np.min(clearances))
    else:
        mean_clear_m = max_clear_m = min_clear_m = 0.0

    similarity_score, sim_diag = gait_similarity(peaks, fs=fs)
    cv = float(sim_diag.get("cv", 0.0)) if isinstance(sim_diag, dict) else 0.0
    asymmetry = float(sim_diag.get("asymmetry", 0.0)) if isinstance(sim_diag, dict) else 0.0

    classification, class_conf = classify_gait(
        cadence=cadence_spm,
        mean_clearance_cm=mean_clear_m * 100,
        asymmetry=asymmetry,
        cv=cv,
    )

    stride_len_m = estimate_stride_length_m(mean_clear_m)
    walking_speed_mps = stride_len_m * (cadence_spm / 60.0) if cadence_spm > 0 else 0.0
    sit_stands = detect_sit_stand_transitions(window, fs=fs)
    intensity = movement_intensity(window, assume_si=is_si)
    j_rms = jerk_rms(window, fs=fs, assume_si=is_si)
    stance_ratio = float(stance_mask.mean()) if len(stance_mask) else 0.0

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "duration_s": duration_s,
            "sample_rate_hz": fs,
            "n_samples": len(window),
        },
        "state": state,
        "metrics": {
            "step_count": step_count,
            "cadence_spm": float(cadence_spm),
            "foot_clearance_mean_cm": mean_clear_m * 100,
            "foot_clearance_min_cm": min_clear_m * 100,
            "foot_clearance_max_cm": max_clear_m * 100,
            "gait_similarity_score": similarity_score,
            "gait_similarity_diagnostics": sim_diag,
            "gait_classification": classification,
            "gait_classification_confidence": float(class_conf),
            "stride_length_m_est": stride_len_m,
            "walking_speed_mps_est": walking_speed_mps,
            "sit_stand_transitions": sit_stands,
            "movement_intensity_mps2": intensity,
            "jerk_rms_mps3": j_rms,
            "stance_phase_fraction": stance_ratio,
        },
        "signals": {
            "step_peak_indices": peaks.tolist(),
            "filtered_accel_magnitude": mag_filt.tolist(),
            "stance_mask": stance_mask.astype(int).tolist(),
            "foot_clearance_per_stride_cm": (clearances * 100).tolist(),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=os.path.join(DEFAULT_DATA_DIR, "walking.csv"),
                        help="CSV with raw IMU data (default: data/walking.csv).")
    parser.add_argument("--has-header", action="store_true",
                        help="Set if the CSV has a header row.")
    parser.add_argument("--offset", type=float, default=0.0,
                        help="Start offset in seconds into the file.")
    parser.add_argument("--seconds", type=float, default=10.0,
                        help="Window length in seconds (default: 10).")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--metadata", default=DEFAULT_METADATA)
    parser.add_argument("--output", default=os.path.join(HERE, "insights.json"),
                        help="Where to write the JSON insight record.")
    args = parser.parse_args(argv)

    with open(args.metadata) as f:
        metadata = json.load(f)

    model = joblib.load(args.model)

    # Auto-detect header for the canonical (mac_timestamp,esp32_ms,...) format.
    has_header = args.has_header
    if not has_header:
        with open(args.input) as f:
            first = f.readline().strip().lower()
        if first.startswith("mac_timestamp") or "esp32_ms" in first or "ax,ay" in first:
            has_header = True

    df, fs, is_si = load_data(args.input, has_header=has_header)
    print(f"Loaded {len(df):,} samples at ~{fs} Hz "
          f"({'physical units' if is_si else 'raw counts'}) from {args.input}")

    win_size = metadata.get("window_size", 100)
    min_seconds = win_size / fs
    seconds = args.seconds
    if seconds * fs < win_size:
        print(f"  Requested {seconds}s @ {fs}Hz = {int(seconds*fs)} samples, "
              f"but model needs ≥ {win_size}. Stretching window to {min_seconds:.1f}s.")
        seconds = min_seconds

    window = slice_window(df, fs=fs, seconds=seconds, offset_s=args.offset)

    insights = analyze_window(window, fs=fs, model=model, metadata=metadata,
                              is_si=is_si)
    insights["source"] = {
        "input_file": os.path.abspath(args.input),
        "offset_s": args.offset,
    }

    with open(args.output, "w") as f:
        json.dump(insights, f, indent=2)

    m = insights["metrics"]
    s = insights["state"]
    print(f"Wrote {args.output}")
    print(f"  state={s['predicted_state']} (conf={s['confidence']:.2f})")
    print(f"  steps={m['step_count']}  cadence={m['cadence_spm']:.1f} spm")
    print(f"  clearance mean={m['foot_clearance_mean_cm']:.1f} cm")
    print(f"  similarity={m['gait_similarity_score']}  classification={m['gait_classification']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
