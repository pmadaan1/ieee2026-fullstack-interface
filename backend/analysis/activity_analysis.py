"""Run the new activity_model and pd_model on a buffer of raw IMU samples.

Both bundles were trained with the pipeline pasted into the project notes:
  - 6 sensor columns (ax, ay, az, gx, gy, gz) in physical units (m/s², °/s)
  - 2 derived magnitude columns (acc_mag, gyr_mag)
  - 100-sample windows @ 50 Hz (= 2 s) with 50% overlap (step 50)
  - Per column: mean, std, min, max, range, rms, dom_freq + 3 band energies
  - StandardScaler before the LightGBM classifier

Across a 10 s buffer (500 samples) we get up to 9 windows; we run both
models on each, then return the mean-probability class as the period's
prediction. OpenDoor is folded into Walk per requirement.
"""
from __future__ import annotations

import os
import warnings
from typing import Sequence

import joblib
import numpy as np
import pandas as pd

# StandardScaler.transform strips feature names → LGBM warns on every call.
# Harmless; we reindex by name explicitly before scaling.
warnings.filterwarnings('ignore', category=UserWarning, module='sklearn')

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(HERE, "models")

ACTIVITY_BUNDLE = joblib.load(os.path.join(MODELS_DIR, "activity_model.joblib"))
PD_BUNDLE       = joblib.load(os.path.join(MODELS_DIR, "pd_model.joblib"))

# Pulled from the bundles, but pinned here so we fail loudly if a future
# bundle changes shape.
SENSOR_COLS = ['ax', 'ay', 'az', 'gx', 'gy', 'gz']
ACC_COLS    = ['ax', 'ay', 'az']
GYR_COLS    = ['gx', 'gy', 'gz']
FEATURE_INPUT_COLS = SENSOR_COLS + ['acc_mag', 'gyr_mag']

SAMPLE_RATE = 50
WINDOW_SIZE = 100
STEP        = 50
FREQ_BANDS  = ((0.5, 3.0), (3.0, 6.0), (6.0, 10.0))

# Only flag a buffer as parkinsons when the mean P(parkinsons) across all
# sub-windows clears this bar. The model's per-window AUC is ~0.73, so a
# loose threshold floods the UI with false positives. Keep advisory.
PD_FLAG_THRESHOLD = 0.90


def _add_magnitudes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['acc_mag'] = np.sqrt((df[ACC_COLS].values ** 2).sum(axis=1))
    df['gyr_mag'] = np.sqrt((df[GYR_COLS].values ** 2).sum(axis=1))
    return df


def _window_features(window_arr: np.ndarray, col_names: Sequence[str]) -> dict:
    feats = {}
    n = window_arr.shape[0]
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    for i, col in enumerate(col_names):
        x = window_arr[:, i]
        feats[f'{col}_mean']  = float(x.mean())
        feats[f'{col}_std']   = float(x.std())
        feats[f'{col}_min']   = float(x.min())
        feats[f'{col}_max']   = float(x.max())
        feats[f'{col}_range'] = float(x.max() - x.min())
        feats[f'{col}_rms']   = float(np.sqrt(np.mean(x ** 2)))
        spec = np.abs(np.fft.rfft(x - x.mean()))
        dom_bin = 1 + int(np.argmax(spec[1:])) if len(spec) > 1 else 0
        feats[f'{col}_dom_freq'] = float(freqs[dom_bin])
        for low, high in FREQ_BANDS:
            mask = (freqs >= low) & (freqs < high)
            feats[f'{col}_energy_{low}-{high}Hz'] = float(np.sum(spec[mask] ** 2))
    return feats


def _extract_features(df: pd.DataFrame) -> pd.DataFrame:
    df = _add_magnitudes(df)
    arr = df[FEATURE_INPUT_COLS].to_numpy()
    rows = []
    for start in range(0, len(arr) - WINDOW_SIZE + 1, STEP):
        window = arr[start:start + WINDOW_SIZE]
        if np.isnan(window).any():
            continue
        rows.append(_window_features(window, FEATURE_INPUT_COLS))
    return pd.DataFrame(rows)


def _predict_distribution(bundle: dict, features: pd.DataFrame) -> tuple[str | None, float, dict]:
    """Returns (top_class, top_confidence_0_to_1, distribution_dict)."""
    if features.empty:
        return None, 0.0, {}
    X = features.reindex(columns=bundle['feature_cols'], fill_value=0.0).values
    X_scaled = bundle['scaler'].transform(X)
    proba = bundle['model'].predict_proba(X_scaled)
    classes = list(bundle['model'].classes_)
    mean_p = proba.mean(axis=0)
    top_idx = int(np.argmax(mean_p))
    return classes[top_idx], float(mean_p[top_idx]), {c: float(p) for c, p in zip(classes, mean_p)}


# Map raw activity classes to user-facing labels. OpenDoor → Walk per spec.
ACTIVITY_LABEL_MAP = {
    'Walk':      'Walking',
    'OpenDoor':  'Walking',     # merged
    'Turn':      'Turning',
    'Standing':  'Standing',
    'Stairs':    'Stairs',
    'Chair':     'Sitting',
    'unlabeled': 'Unknown',
}


def predict_buffer(rows: list[dict]) -> dict:
    """Run both models against a list of raw IMU dicts in physical units.

    Each row must have keys ax, ay, az, gx, gy, gz (m/s², °/s).
    Returns:
        {
          "activity":              "Walking",
          "activity_confidence":   87,
          "activity_distribution": {"Walking": 78.2, "Turning": 5.1, ...},
          "parkinsons":            "control" | "parkinsons" | None,
          "parkinsons_confidence": 73,
        }
    """
    empty = {
        "activity": None, "activity_confidence": None,
        "activity_distribution": {},
        "parkinsons": None, "parkinsons_confidence": None,
    }
    if not rows or len(rows) < WINDOW_SIZE:
        return empty

    df = pd.DataFrame([{
        'ax': r['ax'], 'ay': r['ay'], 'az': r['az'],
        'gx': r['gx'], 'gy': r['gy'], 'gz': r['gz'],
    } for r in rows])

    feats = _extract_features(df)
    if feats.empty:
        return empty

    # ---- activity ----
    act_top, act_conf, act_dist = _predict_distribution(ACTIVITY_BUNDLE, feats)
    if 'OpenDoor' in act_dist:
        act_dist['Walk'] = act_dist.get('Walk', 0.0) + act_dist.pop('OpenDoor')
    if act_top == 'OpenDoor':
        act_top = 'Walk'
        act_conf = act_dist.get('Walk', act_conf)
    activity_label = ACTIVITY_LABEL_MAP.get(act_top, act_top)
    activity_dist_labeled = {ACTIVITY_LABEL_MAP.get(k, k): round(v * 100, 1)
                             for k, v in act_dist.items()}

    # ---- parkinsons ----
    # Always report parkinsons_confidence as P(parkinsons) so the long-term
    # likelihood chart shows the true underlying signal. The label flips to
    # "parkinsons" only when that probability clears PD_FLAG_THRESHOLD.
    _, _, pd_dist = _predict_distribution(PD_BUNDLE, feats)
    pd_prob = pd_dist.get('parkinsons', 0.0)
    pd_label = 'parkinsons' if pd_prob >= PD_FLAG_THRESHOLD else 'control'

    return {
        "activity":              activity_label,
        "activity_confidence":   round(act_conf * 100),
        "activity_distribution": activity_dist_labeled,
        "parkinsons":            pd_label,
        "parkinsons_confidence": round(pd_prob * 100),
    }
