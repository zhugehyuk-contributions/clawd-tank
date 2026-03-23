"""TCP network client for forwarding local session events to a remote server."""

import asyncio
import json
import logging
import socket

logger = logging.getLogger("clawd-tank.network")

NETWORK_RETRY_INTERVAL = 5  # seconds


class NetworkClient:
    """Connects to a remote Clawd Tank server and forwards session events."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 19873,
        hostname: str = "",
        on_connect_cb=None,
        on_disconnect_cb=None,
        retry_interval: float = NETWORK_RETRY_INTERVAL,
    ):
        self._host = host
        self._port = port
        self._hostname = hostname or socket.gethostname()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._on_connect_cb = on_connect_cb
        self._on_disconnect_cb = on_disconnect_cb
        self._retry_interval = retry_interval
        self._lock = asyncio.Lock()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Connect to the server with retry. Performs hello/welcome handshake."""
        if self._writer is not None:
            await self.disconnect()
        while True:
            try:
                logger.info("Connecting to server at %s:%d...", self._host, self._port)
                self._reader, self._writer = await asyncio.open_connection(
                    self._host, self._port
                )
                # Handshake
                hello = json.dumps({"type": "hello", "hostname": self._hostname}) + "\n"
                self._writer.write(hello.encode("utf-8"))
                await self._writer.drain()

                welcome_line = await asyncio.wait_for(
                    self._reader.readline(), timeout=5.0
                )
                if not welcome_line:
                    raise ConnectionError("Server closed during handshake")

                welcome = json.loads(welcome_line.decode("utf-8"))
                if welcome.get("type") != "welcome":
                    raise ConnectionError(f"Unexpected handshake response: {welcome}")

                self._connected = True
                server_name = welcome.get("server", "unknown")
                logger.info("Connected to server: %s", server_name)
                if self._on_connect_cb:
                    self._on_connect_cb()
                return
            except (ConnectionRefusedError, OSError, ConnectionError, asyncio.TimeoutError) as e:
                logger.debug("Server not available: %s, retrying in %ds...", e, self._retry_interval)
                await asyncio.sleep(self._retry_interval)

    async def disconnect(self) -> None:
        """Close the TCP connection."""
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None

    async def forward_message(self, msg: dict) -> bool:
        """Forward a daemon message to the server. Returns True on success."""
        async with self._lock:
            if not self.is_connected:
                return False
            try:
                line = json.dumps(msg) + "\n"
                self._writer.write(line.encode("utf-8"))
                await self._writer.drain()
                return True
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                logger.error("Forward to server failed: %s", e)
                self._connected = False
                if self._on_disconnect_cb:
                    self._on_disconnect_cb()
                return False
