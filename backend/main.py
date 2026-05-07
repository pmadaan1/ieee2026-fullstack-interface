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


def disconnected_payload() -> str:
    return json.dumps({
        "connected": False,
        "timestamp": None,
        "raw": None,
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
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


async def ble_loop():
    while True:
        try:
            await ble.connect()
            async for row in ble.read_loop():
                payload = json.dumps({
                    "connected": True,
                    "timestamp": row["mac_timestamp"],
                    "raw": {
                        "ax": row["ax"],
                        "ay": row["ay"],
                        "az": row["az"],
                        "gx": row["gx"],
                        "gy": row["gy"],
                        "gz": row["gz"],
                    },
                    # Placeholder until the model is wired in —
                    # teammate replaces these Nones with computed values
                    "metrics": {
                        "cadence":        None,
                        "steps":          None,
                        "clearance":      None,
                        "similarity":     None,
                        "classification": None,
                        "confidence":     None,
                    },
                })
                await broadcast(payload)

        except Exception as e:
            print(f"BLE error: {e}")
            await broadcast(disconnected_payload())
            await asyncio.sleep(3)  # wait before retrying


@app.on_event("startup")
async def startup():
    asyncio.create_task(ble_loop())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)

    # Send current connection state immediately on join
    if not ble.connected:
        await websocket.send_text(disconnected_payload())

    try:
        while True:
            await websocket.receive_text()  # keep the connection alive
    except WebSocketDisconnect:
        clients.discard(websocket)
