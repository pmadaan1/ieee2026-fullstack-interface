# SteadyStep — Run Instructions

Real-time gait monitoring dashboard. The browser connects directly to the ESP32 over Web Bluetooth, forwards raw IMU data to a Python backend for signal processing, and displays the resulting metrics.

```
ESP32 (SteadyStep-IMU) ←— Web Bluetooth —→ Browser
                                                ↕ WebSocket
                                            Backend (signal processing)
```

**Important:** Web Bluetooth only works in Chrome or Edge. Safari and Firefox are not supported.

---

## Backend

Requires Python 3.10+. Handles signal processing only — no Bluetooth required.

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The server starts at `http://localhost:8000`. The WebSocket endpoint is `ws://localhost:8000/ws`.

---

## Frontend

Requires Node 18+.

```bash
cd frontend
npm install   # first time only
npm start
```

Opens at `http://localhost:3000`. Press **Scan** in the browser to connect to `SteadyStep-IMU` via Bluetooth. Chrome will show a device picker popup — select the device and confirm.

---

## Project structure

```
ieee2026-fullstack-interface/
├── frontend/        ← React app (Web Bluetooth + display)
│   ├── src/
│   ├── public/
│   └── package.json
└── backend/         ← FastAPI signal processing server
    ├── main.py
    └── requirements.txt
```

---

## Typical startup order

1. Power on the ESP32
2. Start the backend (`uvicorn ...`)
3. Start the frontend (`npm start`)
4. Open Chrome and press **Scan**
