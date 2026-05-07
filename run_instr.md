# SteadyStep — Run Instructions

Real-time gait monitoring dashboard. An ESP32 IMU streams accelerometer and gyroscope data over BLE to a Python backend, which processes the signals and pushes metrics to a React frontend via WebSocket.

```
ESP32 (SteadyStep-IMU) → Bluetooth → Python backend → WebSocket → React app
```

---

## Backend

Requires Python 3.10+.

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The server starts at `http://localhost:8000`. The WebSocket endpoint is `ws://localhost:8000/ws`.

The backend sits idle until the Scan button is pressed in the frontend. If the ESP32 is not found, it reports back and waits for another scan attempt.

---

## Frontend

Requires Node 18+.

```bash
cd frontend
npm install   # first time only
npm start
```

Opens at `http://localhost:3000`. The app connects to the backend WebSocket automatically. Press **Scan** in the UI to initiate a BLE search for `SteadyStep-IMU`.

---

## Project structure

```
ieee2026-fullstack-interface/
├── frontend/        ← React app
│   ├── src/
│   ├── public/
│   └── package.json
└── backend/         ← FastAPI + BLE reader
    ├── main.py
    ├── ble_reader.py
    └── requirements.txt
```

---

## Typical startup order

1. Power on the ESP32
2. Start the backend (`uvicorn ...`)
3. Start the frontend (`npm start`)
4. Press **Scan** in the browser
