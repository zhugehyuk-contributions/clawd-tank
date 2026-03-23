"""Contract tests for NetworkClient and hybrid mode (Scenarios 4, 8).

RED state: all tests must fail until implementation exists.
"""

import asyncio
import json
import pytest
from pathlib import Path

# These imports will fail until implementation exists (RED state)
# from clawd_tank_daemon.network_client import NetworkClient


# ============================================================
# Scenario 4 — Hybrid Client Forward + Local Display
# ============================================================

# Trace: Scenario 4, Section 3b — forward AND local processing
@pytest.mark.asyncio
async def test_hybrid_local_display_and_forward():
    """In client mode, hook message must be processed locally AND forwarded."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    from clawd_tank_daemon.network_client import NetworkClient

    forwarded = []

    class FakeNetworkClient:
        is_connected = True
        async def forward_message(self, msg):
            forwarded.append(msg)
            return True

    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()
    daemon._network_client = FakeNetworkClient()

    msg = {"event": "tool_use", "session_id": "s1", "tool_name": "Edit", "project": "proj"}
    await daemon._handle_message(msg)

    # Local: session state updated
    assert "s1" in daemon._session_states
    # Remote: forwarded to server
    assert len(forwarded) == 1
    assert forwarded[0]["event"] == "tool_use"


# Trace: Scenario 4, Section 5 — forward fails, local continues
@pytest.mark.asyncio
async def test_hybrid_forward_failure_local_continues():
    """If forward fails, local processing must still complete."""
    from clawd_tank_daemon.daemon import ClawdDaemon

    class FailingNetworkClient:
        is_connected = True
        async def forward_message(self, msg):
            raise ConnectionError("server down")

    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()
    daemon._network_client = FailingNetworkClient()

    msg = {"event": "tool_use", "session_id": "s1", "tool_name": "Bash", "project": "proj"}
    await daemon._handle_message(msg)

    # Local must still work
    assert "s1" in daemon._session_states
    assert daemon._session_states["s1"]["state"] == "working"


# Trace: Scenario 4, Section 5 — no client configured
@pytest.mark.asyncio
async def test_hybrid_no_client_local_only():
    """Without NetworkClient, message must be processed locally only."""
    from clawd_tank_daemon.daemon import ClawdDaemon

    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()
    # daemon._network_client is None by default

    msg = {"event": "tool_use", "session_id": "s1", "tool_name": "Edit", "project": "proj"}
    await daemon._handle_message(msg)

    assert "s1" in daemon._session_states


# Trace: Scenario 4, Section 3c — forward sends JSON + newline
@pytest.mark.asyncio
async def test_forward_message_sends_json_newline():
    """NetworkClient.forward_message must write JSON + newline to stream."""
    from clawd_tank_daemon.network_client import NetworkClient

    written_data = bytearray()

    class FakeWriter:
        def write(self, data):
            written_data.extend(data)
        async def drain(self):
            pass
        def is_closing(self):
            return False

    client = NetworkClient.__new__(NetworkClient)
    client._writer = FakeWriter()
    client._connected = True
    client._lock = asyncio.Lock()

    msg = {"event": "session_start", "session_id": "s1"}
    result = await client.forward_message(msg)

    assert result is True
    line = written_data.decode()
    assert line.endswith("\n")
    parsed = json.loads(line.strip())
    assert parsed["event"] == "session_start"


# ============================================================
# Scenario 8 — Menu Bar Network Submenu (Preferences)
# ============================================================

# Trace: Scenario 8, Section 3d — preferences saved
def test_preferences_network_mode_saved(tmp_path):
    """Network mode setting must be persisted to preferences.json."""
    from clawd_tank_menubar.preferences import load_preferences, save_preferences

    prefs_path = tmp_path / "preferences.json"

    save_preferences(
        prefs_path,
        {"network_mode": "client", "network_server_host": "192.168.1.10"},
    )
    loaded = load_preferences(path=prefs_path)
    assert loaded["network_mode"] == "client"
    assert loaded["network_server_host"] == "192.168.1.10"


# Trace: Scenario 8, Section 3a — server mode starts listener
@pytest.mark.asyncio
async def test_server_mode_starts_listener():
    """Switching to server mode must start NetworkServer."""
    from clawd_tank_daemon.daemon import ClawdDaemon

    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon.start_network_server(port=0)
    try:
        assert daemon._network_server is not None
        assert daemon._network_server.port > 0
    finally:
        await daemon.stop_network_server()
    assert daemon._network_server is None


# Trace: Scenario 8, Section 3b — client mode creates client
@pytest.mark.asyncio
async def test_client_mode_creates_client():
    """Setting network client must store reference in daemon."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    from clawd_tank_daemon.network_client import NetworkClient

    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    client = NetworkClient.__new__(NetworkClient)
    client._connected = False
    daemon.set_network_client(client)
    assert daemon._network_client is client


# Trace: Scenario 8, Section 3a+3b — mode switch stops previous
@pytest.mark.asyncio
async def test_mode_switch_stops_previous():
    """Switching from server to client must stop NetworkServer."""
    from clawd_tank_daemon.daemon import ClawdDaemon

    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon.start_network_server(port=0)
    assert daemon._network_server is not None

    await daemon.stop_network_server()
    assert daemon._network_server is None
