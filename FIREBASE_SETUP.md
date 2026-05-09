# Firebase setup for SteadyStep long-term storage

The app works fully without Firebase — long-term storage just disables.
Follow these steps to enable the Long-term tab.

## 1. Create the Firebase project

1. Go to https://console.firebase.google.com → **Add project**.
2. Name it (e.g. `steadystep-dev`). Disable Analytics if you don't need it.
3. In the project, **Build → Firestore Database → Create database**.
   Start in **production** mode, pick a region close to you.

## 2. Backend credentials (writes)

The backend writes per-minute aggregates using the Firebase Admin SDK.

1. Project Settings (gear icon, top-left) → **Service accounts** tab.
2. Click **Generate new private key** → confirm. A JSON file downloads.
3. Move it into the backend:
   ```bash
   mv ~/Downloads/steadystep-dev-firebase-adminsdk-*.json \
      backend/firebase-credentials.json
   ```
   (The filename `firebase-credentials.json` is what the code looks for by default.
    It's already gitignored.)
4. Install the Admin SDK:
   ```bash
   cd backend
   ./venv/bin/pip install -r requirements.txt
   ```
5. Restart the backend:
   ```bash
   ./venv/bin/python -m uvicorn main:app --reload --port 8000
   ```
   On startup you should see:
   ```
   firebase_store: initialized (creds=.../firebase-credentials.json)
   ```

To override the default user ID for writes:
```bash
FIREBASE_USER_ID=alice ./venv/bin/python -m uvicorn main:app ...
```

## 3. Frontend config (reads)

The frontend reads from Firestore using the Web SDK. These values are
**public** — they identify your project but don't grant access on their
own (that's Firestore Rules' job).

1. In Firebase Console: Project Settings → **General** tab.
2. Scroll to **Your apps** → if no web app exists, click the `</>` icon
   to register one. Name it whatever; you don't need Hosting.
3. Copy the `firebaseConfig` object that appears.
4. Create `frontend/.env.local` (already gitignored) by copying the
   example:
   ```bash
   cp frontend/.env.local.example frontend/.env.local
   ```
   Fill in the six `REACT_APP_FIREBASE_*` values from the config.
5. Install the firebase package:
   ```bash
   cd frontend
   npm install
   ```
6. Restart `npm start`. The Long-term tab will now query Firestore.

## 4. Firestore security rules

The default production rules deny everything. For demo use (single user),
paste this in **Firestore → Rules** and click **Publish**:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{uid}/{document=**} {
      // Demo: allow anyone to read/write the demo-user docs.
      // Replace with auth-based rules before going to production.
      allow read, write: if uid == "demo-user";
    }
  }
}
```

When you add Firebase Auth later, replace with:
```
allow read, write: if request.auth.uid == uid;
```

## 5. What gets stored

```
users/demo-user/minutes/{epoch_ms}
  ts_ms, minute_iso, ticks,
  cadence, speed, stride, clearance,
  asymmetry, variability, stance_pct, stance_time, swing_time, step_time,
  intensity, jerk, steps_total,
  classification_majority, state_majority,
  classification_counts: {Normal: 90, Unsteady: 8, ...},
  state_counts: {walking: 100, ...}
```

One doc per minute of **active** data — pure-idle minutes are skipped so
the database doesn't fill with zeros.

## 6. Scaling note (6-month view)

Per-minute granularity for 6 months of heavy use can hit thousands of
docs per range query (currently capped at 5000). When you start brushing
that limit, add a Cloud Function that rolls minute docs into daily
summaries:

```
users/{uid}/daily/{YYYY-MM-DD}
  date, walking_minutes, avg_cadence, avg_speed, avg_stride,
  avg_clearance, avg_asymmetry, avg_variability,
  classification_distribution: {...}
```

Then update `LongTermView.jsx` to query `daily/` for the 6-month range
and `minutes/` for week/month. Not built yet — flagged as next step.
