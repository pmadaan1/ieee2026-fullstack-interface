import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from ble_reader import BLEReader

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

clients: set[WebSocket] = set()
ble = BLEReader()
scanning = False


def status_payload(connected: bool, scanning: bool) -> str:
    return json.dumps({
        "connected": connected,
        "scanning":  scanning,
        "timestamp": None,
        "raw":       None,
        "metrics": {
            "cadence":        None,
            "steps":          None,
            "clearance":      None,
            "similarity":     None,
            "classification": None,
            "confidence":     None,
        },
    })


async def broadcast(payload: str):
    dead: set[WebSocket] = set()
    for ws in clients:
        try:
            # sends JSON to the React frontend over WebSocket
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


async def scan_and_connect():
    global scanning
    scanning = True
    await broadcast(status_payload(connected=False, scanning=True))  # tell frontend we're scanning

    try:
        await ble.connect()
        scanning = False

        async for row in ble.read_loop():
            payload = json.dumps({
                "connected": True,
                "scanning":  False,
                "timestamp": row["mac_timestamp"],
                "raw": {                          # raw IMU frame straight from ESP32
                    "ax": row["ax"],
                    "ay": row["ay"],
                    "az": row["az"],
                    "gx": row["gx"],
                    "gy": row["gy"],
                    "gz": row["gz"],
                },
                "metrics": {                      # teammate fills these in from the model
                    "cadence":        None,
                    "steps":          None,
                    "clearance":      None,
                    "similarity":     None,
                    "classification": None,
                    "confidence":     None,
                },
            })
            await broadcast(payload)              # push live frame to frontend

    except Exception as e:
        print(f"BLE error: {e}")
    finally:
        scanning = False
        await broadcast(status_payload(connected=False, scanning=False))  # notify frontend of disconnect


@app.post("/scan")
async def trigger_scan():
    global scanning
    if scanning or ble.connected:
        return {"status": "already active"}
    asyncio.create_task(scan_and_connect())
    return {"status": "scanning"}


@app.post("/disconnect")
async def trigger_disconnect():
    if not ble.connected:
        return {"status": "not connected"}
    await ble.disconnect()
    return {"status": "disconnected"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    await websocket.send_text(status_payload(connected=ble.connected, scanning=scanning))  # sync new tab to current state
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.discard(websocket)
