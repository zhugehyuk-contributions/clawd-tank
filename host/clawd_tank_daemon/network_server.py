"""TCP network server for receiving remote session events."""

import asyncio
import json
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

logger = logging.getLogger("clawd-tank.network")

NETWORK_DEFAULT_PORT = 19873
HANDSHAKE_TIMEOUT = 5.0


@dataclass
class ClientSession:
    """Tracks a connected remote client."""
    hostname: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    connected_at: float = field(default_factory=time.time)
    last_message: float = field(default_factory=time.time)


class NetworkServer:
    """TCP server that accepts remote client connections and routes session events."""

    def __init__(
        self,
        port: int = NETWORK_DEFAULT_PORT,
        on_message: Optional[Callable[[str, dict], Awaitable[None]]] = None,
        on_client_change: Optional[Callable[[list[str]], None]] = None,
        on_client_disconnect: Optional[Callable[[str], None]] = None,
    ):
        self._port = port
        self._on_message = on_message
        self._on_client_change = on_client_change
        self._on_client_disconnect = on_client_disconnect
        self._server: Optional[asyncio.Server] = None
        self._clients: dict[str, ClientSession] = {}
        self._hostname = socket.gethostname()

    @property
    def port(self) -> int:
        """Return the actual listening port (useful when port=0)."""
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    @property
    def is_listening(self) -> bool:
        return self._server is not None and self._server.is_serving()

    def get_client_list(self) -> list[str]:
        """Return list of connected client hostnames."""
        return list(self._clients.keys())

    async def start(self) -> None:
        """Start listening for TCP connections."""
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self._port
        )
        actual_port = self.port
        logger.info("Network server listening on 0.0.0.0:%d", actual_port)

    async def stop(self) -> None:
        """Stop the server and disconnect all clients."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        # Close all client connections
        for session in list(self._clients.values()):
            try:
                session.writer.close()
                await session.writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()
        logger.info("Network server stopped")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single client connection: handshake then message loop."""
        addr = writer.get_extra_info("peername", ("?", 0))
        hostname = None
        try:
            hostname = await self._do_handshake(reader, writer, addr)
            if hostname is None:
                return

            # Message loop
            while True:
                line = await reader.readline()
                if not line:
                    break  # EOF
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    logger.warning("Malformed JSON from %s, skipping", hostname)
                    continue

                if hostname in self._clients:
                    self._clients[hostname].last_message = time.time()

                if self._on_message:
                    try:
                        await self._on_message(hostname, msg)
                    except Exception:
                        logger.exception("Error handling message from %s", hostname)

        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        except asyncio.CancelledError:
            pass
        finally:
            if hostname and hostname in self._clients:
                del self._clients[hostname]
                logger.info("Network client disconnected: %s", hostname)
                if self._on_client_disconnect:
                    self._on_client_disconnect(hostname)
                if self._on_client_change:
                    self._on_client_change(self.get_client_list())
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _do_handshake(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        addr: tuple,
    ) -> Optional[str]:
        """Perform hello/welcome handshake. Returns hostname or None on failure."""
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=HANDSHAKE_TIMEOUT)
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("Handshake timeout from %s", addr)
            return None

        if not line:
            return None

        try:
            hello = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            logger.warning("Handshake: malformed JSON from %s", addr)
            return None

        if hello.get("type") != "hello" or not hello.get("hostname"):
            logger.warning("Handshake: invalid hello from %s: %s", addr, hello)
            return None

        hostname = hello["hostname"]

        # Replace existing connection with same hostname
        if hostname in self._clients:
            old = self._clients[hostname]
            logger.warning("Replacing existing connection for %s", hostname)
            try:
                old.writer.close()
                await old.writer.wait_closed()
            except Exception:
                pass

        # Send welcome
        welcome = json.dumps({"type": "welcome", "server": self._hostname}) + "\n"
        writer.write(welcome.encode("utf-8"))
        await writer.drain()

        # Register client
        session = ClientSession(hostname=hostname, reader=reader, writer=writer)
        self._clients[hostname] = session

        logger.info("Network client connected: %s from %s", hostname, addr)
        if self._on_client_change:
            self._on_client_change(self.get_client_list())

        return hostname
