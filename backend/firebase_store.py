"""Firebase Firestore writer for SteadyStep long-term storage.

Storage model
-------------
users/{uid}/minutes/{epoch_ms}   one doc per minute of activity (averaged
                                  across the ~120 analysis ticks in that
                                  minute when running at 0.5 s cadence).

Each doc looks like:
    {
      ts_ms, minute_iso, ticks,
      cadence, speed, stride, clearance,
      asymmetry, variability,
      stance_pct, stance_time, swing_time, step_time,
      intensity, jerk, steps_total,
      classification_majority, state_majority,
      classification_counts: {Normal: 90, Unsteady: 8, ...},
      state_counts: {walking: 100, running: 5, ...},
    }

Setup
-----
1. Create a Firebase project at console.firebase.google.com.
2. Enable Firestore in production mode.
3. Project Settings → Service Accounts → Generate new private key.
4. Save the downloaded JSON to backend/firebase-credentials.json
   (already gitignored).
5. Set env var:
       export FIREBASE_CREDENTIALS=./firebase-credentials.json
   (or rely on the default path resolution below).

Without credentials, every write becomes a no-op so the live pipeline
still runs in dev environments.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

logger = logging.getLogger("firebase_store")

# Lazy import — firebase_admin is heavy and optional in dev.
_db = None
_initialized = False
_disabled = False


def init() -> None:
    """Initialize firebase-admin once, idempotent. Safe to call repeatedly.

    Credentials are loaded from (in order):
      1. FIREBASE_CREDENTIALS_JSON env var — raw JSON string. Use this for
         hosted environments (Railway, Heroku, etc.) where you can't ship
         a file. Paste the entire service-account JSON into one variable.
      2. FIREBASE_CREDENTIALS env var — filesystem path to the JSON.
         Defaults to backend/firebase-credentials.json for local dev.

    If neither is available, the store stays disabled and all writes are
    no-ops, so the live pipeline still runs.
    """
    global _db, _initialized, _disabled
    if _initialized:
        return
    _initialized = True

    try:
        from firebase_admin import credentials, firestore, initialize_app
    except ImportError:
        print("[firebase_store] firebase-admin not installed — long-term storage DISABLED.")
        _disabled = True
        return

    cred = None
    source = None

    # Option 1: full JSON pasted into an env var.
    raw_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if raw_json:
        import json as _json
        try:
            cred = credentials.Certificate(_json.loads(raw_json))
            source = "FIREBASE_CREDENTIALS_JSON env var"
        except Exception as exc:
            print(f"[firebase_store] FIREBASE_CREDENTIALS_JSON failed to parse ({exc}) — disabled.")
            _disabled = True
            return

    # Option 2: filesystem path (local dev default).
    if cred is None:
        cred_path = os.environ.get(
            "FIREBASE_CREDENTIALS",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase-credentials.json"),
        )
        if not os.path.exists(cred_path):
            print(f"[firebase_store] no credentials found "
                  f"(checked FIREBASE_CREDENTIALS_JSON env var, then {cred_path}) — DISABLED.")
            _disabled = True
            return
        try:
            cred = credentials.Certificate(cred_path)
            source = os.path.basename(cred_path)
        except Exception as exc:
            print(f"[firebase_store] credentials file failed to load ({exc}) — disabled.")
            _disabled = True
            return

    try:
        initialize_app(cred)
        _db = firestore.client()
        print(f"[firebase_store] ENABLED — credentials from {source}")
    except Exception as exc:                        # pylint: disable=broad-except
        print(f"[firebase_store] init FAILED ({exc}) — long-term storage disabled.")
        _disabled = True


def is_enabled() -> bool:
    return _db is not None and not _disabled


# ----------------------------- aggregation ------------------------------

NUMERIC_FIELDS = (
    "cadence", "speed", "stride", "clearance",
    "asymmetry", "variability",
    "stance_pct", "stance_time", "swing_time", "step_time",
    "intensity", "jerk",
    "parkinsons_confidence",         # mean PD likelihood over the minute (0–100)
    "activity_confidence",           # mean confidence of dominant activity
)

CATEGORICAL_FIELDS = (
    "classification",                # gait classification (Normal/Limping/...)
    "state",                         # legacy LGBM state (idle/walking/running)
    "activity",                      # new activity model (Walking/Turning/...)
    "parkinsons",                    # control / parkinsons
)


def aggregate_minute(samples: Iterable[dict]) -> dict:
    """Reduce a minute's worth of analysis ticks into a single doc.

    For numeric fields: mean of non-null values.
    For categorical fields (classification, state): mode + counts.
    Steps: total step count attributed to this minute (rough — sums per-window
    counts, which overlap; treat as relative not absolute).
    """
    samples = [s for s in samples if s is not None]
    if not samples:
        return {}

    out: dict = {"ticks": len(samples)}

    for field in NUMERIC_FIELDS:
        vals = [s.get(field) for s in samples if s.get(field) is not None]
        out[field] = round(sum(vals) / len(vals), 3) if vals else None

    # Counts + majority for categorical fields.
    for field in CATEGORICAL_FIELDS:
        counts: dict[str, int] = {}
        for s in samples:
            v = s.get(field)
            if v is None:
                continue
            counts[v] = counts.get(v, 0) + 1
        out[f"{field}_counts"] = counts
        out[f"{field}_majority"] = max(counts.items(), key=lambda kv: kv[1])[0] if counts else None

    # Steps: total over the minute (sum of per-window counts; not strictly
    # accurate due to window overlap but useful as a proxy).
    steps = [s.get("steps") for s in samples if s.get("steps") is not None]
    out["steps_total"] = int(sum(steps)) if steps else 0

    return out


# ----------------------------- writes ----------------------------------

def write_minute(uid: str, minute_start_ms: int, samples: list[dict]) -> bool:
    """Aggregate `samples` and write one doc to users/{uid}/minutes/{ts}.

    Returns True if written, False if disabled or failed (logged).
    """
    if not is_enabled():
        return False
    if not samples:
        return False
    try:
        agg = aggregate_minute(samples)
        doc = {
            "ts_ms":      minute_start_ms,
            "minute_iso": datetime.fromtimestamp(minute_start_ms / 1000, tz=timezone.utc).isoformat(),
            **agg,
        }
        # Doc ID = epoch ms — keeps natural time ordering.
        _db.collection("users").document(uid) \
            .collection("minutes").document(str(minute_start_ms)) \
            .set(doc)
        ts_iso = datetime.fromtimestamp(minute_start_ms / 1000, tz=timezone.utc).strftime("%H:%M:%SZ")
        print(f"[firebase_store] wrote minute {ts_iso} ({len(samples)} ticks)")
        return True
    except Exception as exc:                        # pylint: disable=broad-except
        print(f"[firebase_store] write_minute FAILED: {exc}")
        return False
