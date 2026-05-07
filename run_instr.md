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

If the ESP32 is not paired, the backend will scan and retry every 3 seconds — no crash. The frontend will show "No signal" until a connection is established.

---

## Frontend

Requires Node 18+.

```bash
npm install   # first time only
npm start
```

Opens at `http://localhost:3000`. The app connects to the backend WebSocket automatically and displays live metrics. All values show `--` until the backend is running and the ESP32 is connected.

---

## Typical startup order

1. Power on the ESP32
2. Start the backend (`uvicorn ...`)
3. Start the frontend (`npm start`)
