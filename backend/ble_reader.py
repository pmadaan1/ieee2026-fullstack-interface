import asyncio
import time
from bleak import BleakClient, BleakScanner

# Configure these to match your ESP32's BLE profile
DEVICE_NAME = "SteadyStep-IMU"
SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"  # Nordic UART Service
CHAR_UUID    = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # NUS TX (ESP32 → Mac, notify)


class BLEReader:
    def __init__(self):
        self._client: BleakClient | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self.connected = False

    async def connect(self):
        print(f"Scanning for '{DEVICE_NAME}'...")
        device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
        if device is None:
            raise RuntimeError(f"Device '{DEVICE_NAME}' not found")

        self._client = BleakClient(device, disconnected_callback=self._on_disconnect)
        await self._client.connect()
        self.connected = True
        print(f"Connected to {device.name}")
        await self._client.start_notify(CHAR_UUID, self._on_data)

    def _on_disconnect(self, _client: BleakClient):
        self.connected = False
        print("BLE disconnected")

    def _on_data(self, _sender, data: bytearray):
        try:
            parts = data.decode().strip().split(",")
            # Expected format from ESP32: esp32_ms,ax,ay,az,gx,gy,gz
            # (mac_timestamp is added here on the Mac side)
            if len(parts) < 7:
                return
            self._queue.put_nowait({
                "mac_timestamp": time.time(),
                "esp32_ms":      int(parts[0]),
                "ax": float(parts[1]),
                "ay": float(parts[2]),
                "az": float(parts[3]),
                "gx": float(parts[4]),
                "gy": float(parts[5]),
                "gz": float(parts[6]),
            })
        except (ValueError, IndexError):
            pass

    async def read_loop(self):
        while self.connected:
            try:
                row = await asyncio.wait_for(self._queue.get(), timeout=2.0)
                yield row
            except asyncio.TimeoutError:
                if not self.connected:
                    break

    async def disconnect(self):
        if self._client and self._client.is_connected:
            await self._client.disconnect()
