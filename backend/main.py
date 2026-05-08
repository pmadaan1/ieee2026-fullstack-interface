import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def process(raw: dict) -> dict:  # noqa: ARG001
    # teammate wires in model here — raw has ax, ay, az, gx, gy, gz
    return {
        "cadence":        None,
        "steps":          None,
        "clearance":      None,
        "similarity":     None,
        "classification": None,
        "confidence":     None,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()       # raw IMU frame from browser
            metrics = process(data.get("raw", {}))
            await websocket.send_text(json.dumps({"metrics": metrics}))  # send processed metrics back
    except WebSocketDisconnect:
        pass
