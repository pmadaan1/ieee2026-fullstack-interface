# -*- coding: utf-8 -*-
"""SteadyStep — train the LGBM gait classifier and run gait analytics on a
captured IMU CSV.

Originally exported from Colab; restructured so it runs as a standalone
script against the canonical CSV format produced by receive_imu_6050.py:

    mac_timestamp, esp32_ms, ax, ay, az, gx, gy, gz

esp32_ms (milliseconds since boot) is the time axis. ax/ay/az are in m/s²
and gx/gy/gz in rad/s — values are already in physical units, so no raw
count → g conversion is needed.

Usage
-----
Run analytics on a captured CSV (default: data/regular_walking_data.csv):
    python steadystepmodel.py
    python steadystepmodel.py --input data/regular_walking_data.csv

Retrain from the kaggle MPU6050 dataset (writes lgbm_model_typeClass +
model_metadata.json next to this file):
    python steadystepmodel.py --train

Note
----
The shipped model was trained at 50 Hz. regular_walking_data.csv is closer
to ~5 Hz, which is well below what the model expects — predictions on data
this slow are mostly indicative. Step detection still works because the
bandpass is clamped to a valid range when fs is low.
"""

from __future__ import annotations

import argparse
import json
import os
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

import joblib
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, find_peaks


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(HERE, "lgbm_model_typeClass")
DEFAULT_METADATA = os.path.join(HERE, "model_metadata.json")
DEFAULT_INPUT = os.path.join(HERE, "data", "regular_walking_data.csv")

# Canonical input column layout — matches receive_imu_6050.py output.
INPUT_COLS = ["mac_timestamp", "esp32_ms", "ax", "ay", "az", "gx", "gy", "gz"]

# The trained model's features were named after the kaggle column scheme,
# so we rename on load to match.
COL_MAP = {
    "esp32_ms": "timestamp",
    "ax": "accel_x", "ay": "accel_y", "az": "accel_z",
    "gx": "gyro_x", "gy": "gyro_y", "gz": "gyro_z",
}

G_MS2 = 9.81


# ---------- feature extraction ---------------------------------------------

def add_magnitude(data, magnitude_groups):
    """Append magnitude channels to the dataframe.

    magnitude_groups: {new_col_name: [axis_columns]}
        e.g. {'accel_mag': ['accel_x', 'accel_y', 'accel_z']}
    """
    data = data.copy()
    for new_col, axes in magnitude_groups.items():
        data[new_col] = np.sqrt(np.sum(data[axes].values ** 2, axis=1))
    return data


def raw_to_windows(data, window_size, step, sample_rate,
                   freq_bands=((0.5, 3.0), (3.0, 6.0))):
    """Slide a window over `data` and compute time- and frequency-domain
    features per column."""
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


def extract_features(dataset, window_size=200, step=100, sample_rate=100):
    raw_imu = dataset.copy()
    data = add_magnitude(raw_imu, {
        "accel_mag": ["accel_x", "accel_y", "accel_z"],
        "gyro_mag":  ["gyro_x",  "gyro_y",  "gyro_z"],
    })
    return raw_to_windows(data, window_size, step, sample_rate)


# ---------- step detection -------------------------------------------------

def detect_steps(data, fs=50):
    """Walking-step peak detection with an adaptive threshold.

    The bandpass cutoff is clamped to (0, fs/2) so this also works when the
    sampling rate is too low for the default 0.5–3.0 Hz band.
    """
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


# ---------- foot clearance -------------------------------------------------

def detect_stance_phases(data, fs=50, accel_var_thresh=None, gyro_mag_thresh=None):
    """Stance phase = foot is flat on ground = low gyro magnitude AND low
    accel variance. Returns a boolean array, True where the foot is in
    stance."""
    gyro_mag = np.sqrt(data["gyro_x"] ** 2 + data["gyro_y"] ** 2 + data["gyro_z"] ** 2)
    accel_mag = np.sqrt(data["accel_x"] ** 2 + data["accel_y"] ** 2 + data["accel_z"] ** 2)

    win = max(int(0.05 * fs), 3)
    accel_var = pd.Series(accel_mag).rolling(win, center=True).var().fillna(0).values

    if gyro_mag_thresh is None:
        gyro_mag_thresh = np.percentile(gyro_mag, 30)
    if accel_var_thresh is None:
        accel_var_thresh = np.percentile(accel_var, 30)

    return (gyro_mag < gyro_mag_thresh) & (accel_var < accel_var_thresh)


def estimate_foot_clearance(data, fs=50, gravity_raw=16384, assume_si=False):
    """Estimate per-step foot clearance using ZUPT.

    `gravity_raw` is the raw accel value corresponding to 1 g (16384 for an
    MPU6050 in ±2g mode). Set `assume_si=True` if `data` is already in m/s².

    Returns: list of clearance heights (in meters), one per stride.
    """
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

    return np.array(clearances)


# ---------- gait similarity / classification -------------------------------

def gait_similarity(peaks, fs=50):
    """Score 1-10 measuring how regular the user's gait is. Higher = more
    consistent stride timing."""
    if len(peaks) < 4:
        return None, "Not enough steps to assess gait similarity"

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

    diagnostics = {
        "cv": float(cv),
        "asymmetry": float(asymmetry),
        "mean_interval_s": float(intervals.mean()),
        "n_steps": int(len(peaks)),
    }
    return float(score_1_to_10), diagnostics


def classify_gait(cadence, mean_clearance_cm, asymmetry, cv):
    if asymmetry > 0.15:
        return "Limping", min(asymmetry / 0.30, 1.0)
    if mean_clearance_cm < 5 and cadence > 110:
        return "Shuffling", min((10 - mean_clearance_cm) / 10, 1.0)
    if cv > 0.12:
        return "Unsteady", min(cv / 0.20, 1.0)
    return "Normal", 1.0 - max(cv / 0.10, asymmetry / 0.10, 0)


# ---------- canonical CSV loading ------------------------------------------

def load_imu_csv(path):
    """Load a captured IMU CSV in canonical format.

    Returns (df, fs) where df has columns
        timestamp, accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z, temperature
    (timestamp = esp32_ms in milliseconds; temperature is filled with a
    constant since the on-foot ESP32 doesn't ship that channel).
    fs is inferred from the median esp32_ms delta.
    """
    df = pd.read_csv(path)
    if "esp32_ms" not in df.columns:
        raise ValueError(
            f"{path} is missing the 'esp32_ms' column. Expected columns: {INPUT_COLS}"
        )
    df = df.rename(columns=COL_MAP)
    out = df[["timestamp", "accel_x", "accel_y", "accel_z",
              "gyro_x", "gyro_y", "gyro_z"]].copy()
    out["temperature"] = 25.0

    dt_ms = np.median(np.diff(out["timestamp"].values))
    if dt_ms <= 0:
        raise ValueError(f"esp32_ms in {path} is not monotonic; cannot infer fs")
    fs = int(round(1000.0 / dt_ms))
    return out, fs


# ---------- inference (run analytics on a captured CSV) --------------------

def run_analysis(csv_path=DEFAULT_INPUT, model_path=DEFAULT_MODEL,
                 metadata_path=DEFAULT_METADATA):
    df, fs = load_imu_csv(csv_path)
    duration_s = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]) / 1000.0
    print(f"Loaded {len(df):,} samples from {csv_path}")
    print(f"Duration: {duration_s:.1f}s   inferred fs ≈ {fs} Hz")
    if fs < 20:
        print(f"  ⚠ fs={fs}Hz is well below the 50Hz training rate — model "
              "predictions are best-effort only.")

    # ----- model prediction over the full capture -----
    model = joblib.load(model_path)
    with open(metadata_path) as f:
        metadata = json.load(f)

    win = metadata.get("window_size", 100)
    overlap = metadata.get("overlap", 50)
    feats = extract_features(df, window_size=win, step=overlap, sample_rate=fs)
    if len(feats) == 0:
        print(f"  ⚠ Not enough samples ({len(df)}) to form even one "
              f"window of {win} samples — skipping model prediction.")
    else:
        X = feats.reindex(columns=metadata["feature_columns"], fill_value=0.0)
        proba = model.predict_proba(X)
        classes = list(model.classes_)
        mean_p = proba.mean(axis=0)
        pred = classes[int(np.argmax(mean_p))]
        print("\nState classification (averaged over all windows):")
        for c, p in sorted(zip(classes, mean_p), key=lambda kv: -kv[1]):
            print(f"  {c:>8s}: {p:.3f}")
        print(f"  → predicted state: {pred} (confidence {mean_p.max():.2f})")

    # ----- step detection / cadence -----
    peaks, _ = detect_steps(df, fs=fs)
    duration_min = duration_s / 60.0
    cadence = len(peaks) / duration_min if duration_min > 0 else 0.0
    print(f"\nSteps detected: {len(peaks)}")
    print(f"Cadence: {cadence:.1f} spm")

    # ----- foot clearance (data is already in m/s², so assume_si=True) -----
    clearances = estimate_foot_clearance(df, fs=fs, assume_si=True)
    if len(clearances) > 0:
        print(f"Foot clearance — mean {clearances.mean()*100:.1f} cm "
              f"(min {clearances.min()*100:.1f}, max {clearances.max()*100:.1f}, "
              f"strides {len(clearances)})")
    else:
        print("Foot clearance — no swing phases detected.")

    # ----- gait similarity / classification -----
    score, diag = gait_similarity(peaks, fs=fs)
    if score is None:
        print(f"Gait similarity: n/a — {diag}")
        cv = 0.0
        asym = 0.0
    else:
        print(f"Gait similarity: {score:.1f}/10  ({diag})")
        cv = diag["cv"]
        asym = diag["asymmetry"]

    mean_clear_cm = float(clearances.mean() * 100) if len(clearances) else 0.0
    label, conf = classify_gait(cadence, mean_clear_cm, asym, cv)
    print(f"Gait classification: {label}  (confidence {conf:.2f})")

    return {
        "fs_hz": fs,
        "duration_s": duration_s,
        "step_count": int(len(peaks)),
        "cadence_spm": float(cadence),
        "foot_clearance_mean_cm": mean_clear_cm,
        "gait_similarity_score": score,
        "gait_classification": label,
    }


# ---------- training (kept for reproducibility) ----------------------------

def train(output_dir=HERE):
    """Retrain the LGBM classifier from the kaggle MPU6050 dataset and write
    lgbm_model_typeClass + model_metadata.json into output_dir.

    Requires kagglehub, lightgbm, sklearn. Only run when you actually want
    to rebuild the model — the day-to-day pipeline uses the saved one.
    """
    import lightgbm as lgb
    import sklearn
    import kagglehub
    from lightgbm import LGBMClassifier
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, roc_auc_score
    from sklearn.model_selection import RandomizedSearchCV, train_test_split
    from sklearn.preprocessing import StandardScaler

    path = kagglehub.dataset_download(
        "letmecook123/mpu6050-body-movement-dataset-walking-running-idle"
    )
    print("Path to dataset files:", path)

    cols = ["timestamp", "accel_x", "accel_y", "accel_z",
            "gyro_x", "gyro_y", "gyro_z", "temperature", "label"]

    walking_df = pd.read_csv(os.path.join(path, "walking.csv"), header=None, names=cols)
    idle_df = pd.read_csv(os.path.join(path, "idle.csv"), header=None, names=cols)
    running_df = pd.read_csv(os.path.join(path, "running.csv"), header=None, names=cols)

    walking_df["label"] = "walking"
    idle_df["label"] = "idle"
    running_df["label"] = "running"

    walking_X = extract_features(walking_df.drop("label", axis=1), 100, 50, sample_rate=50)
    running_X = extract_features(running_df.drop("label", axis=1), 100, 50, sample_rate=50)
    idle_X = extract_features(idle_df.drop("label", axis=1), 100, 50, sample_rate=50)

    X = pd.concat([walking_X, running_X, idle_X], axis=0).reset_index(drop=True)
    y = pd.Series(
        ["walking"] * len(walking_X) + ["running"] * len(running_X) + ["idle"] * len(idle_X)
    )

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=20, stratify=y
    )
    scaler = StandardScaler().fit(X_train)

    grid = {
        "max_depth": [4, 6, 8],
        "n_estimators": [50, 100, 200],
        "learning_rate": [0.05, 0.1],
        "subsample": [0.8, 1.0],
        "reg_lambda": [0.1, 1, 10],
        "colsample_bytree": [0.8, 1.0],
    }
    base = LGBMClassifier(random_state=1, class_weight="balanced", verbose=-1)
    search = RandomizedSearchCV(
        base, grid, n_iter=60, cv=5, scoring="roc_auc_ovr", n_jobs=-1, random_state=1
    )
    search.fit(X_train, y_train)
    best = search.best_estimator_
    print("Best CV AUC:", search.best_score_)
    print("Best params:", search.best_params_)

    proba = best.predict_proba(X_test)
    preds = best.predict(X_test)
    print("Test AUC:", roc_auc_score(y_test, proba, multi_class="ovr"))
    print("Test accuracy:", accuracy_score(y_test, preds))
    print("\nClassification report:")
    print(classification_report(y_test, preds))
    print("Confusion matrix:")
    print(confusion_matrix(y_test, preds))

    joblib.dump(best, os.path.join(output_dir, "lgbm_model_typeClass"))
    joblib.dump(scaler, os.path.join(output_dir, "scaler.pkl"))

    metadata = {
        "feature_columns": list(X_train.columns),
        "classes": list(best.classes_),
        "sampling_rate_hz": 50,
        "window_size": 100,
        "overlap": 50,
        "lightgbm_version": lgb.__version__,
        "sklearn_version": sklearn.__version__,
    }
    with open(os.path.join(output_dir, "model_metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved model + metadata to {output_dir}")


# ---------- entrypoint -----------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help="Path to canonical IMU CSV (default: data/regular_walking_data.csv).")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--metadata", default=DEFAULT_METADATA)
    parser.add_argument("--train", action="store_true",
                        help="Retrain the LGBM model from the kaggle MPU6050 dataset.")
    args = parser.parse_args(argv)

    if args.train:
        train()
    else:
        run_analysis(csv_path=args.input, model_path=args.model,
                     metadata_path=args.metadata)


if __name__ == "__main__":
    main()
