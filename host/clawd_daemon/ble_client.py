"""BLE GATT client for communicating with the Clawd ESP32 device."""

import asyncio
import logging
from bleak import BleakClient, BleakScanner

logger = logging.getLogger("clawd.ble")

SERVICE_UUID = "aecbefd9-98a2-4773-9fed-bb2166daa49a"
NOTIFICATION_CHR_UUID = "71ffb137-8b7a-47c9-9a7a-4b1b16662d9a"
SCAN_INTERVAL_SECS = 5


class ClawdBleClient:
    """Manages BLE connection to the Clawd ESP32 device."""

    def __init__(self):
        self._client: BleakClient | None = None
        self._connected = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self) -> None:
        """Scan for and connect to the Clawd device. Retries until found."""
        while True:
            logger.info("Scanning for Clawd device...")
            device = await BleakScanner.find_device_by_name(
                "Clawd", timeout=SCAN_INTERVAL_SECS
            )
            if device is None:
                logger.debug("Clawd not found, retrying...")
                continue

            logger.info("Found Clawd: %s (%s)", device.name, device.address)
            try:
                client = BleakClient(
                    device,
                    disconnected_callback=self._on_disconnect,
                )
                await client.connect()
                self._client = client
                self._connected.set()
                logger.info("Connected to Clawd (MTU: %d)", client.mtu_size)
                return
            except Exception as e:
                logger.warning("Connection failed: %s, retrying...", e)
                await asyncio.sleep(SCAN_INTERVAL_SECS)

    def _on_disconnect(self, client: BleakClient) -> None:
        logger.warning("Disconnected from Clawd")
        self._connected.clear()
        self._client = None

    async def ensure_connected(self) -> None:
        """Reconnect if disconnected."""
        if not self.is_connected:
            await self.connect()

    async def write_notification(self, payload: str) -> bool:
        """Write a JSON payload to the notification characteristic.

        Returns True on success, False on failure.
        """
        async with self._lock:
            if not self.is_connected:
                logger.warning("Not connected, cannot write")
                return False
            try:
                data = payload.encode("utf-8")
                await self._client.write_gatt_char(
                    NOTIFICATION_CHR_UUID, data, response=False
                )
                logger.debug("Wrote %d bytes to BLE", len(data))
                return True
            except Exception as e:
                logger.error("BLE write failed: %s", e)
                return False

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        self._connected.clear()
