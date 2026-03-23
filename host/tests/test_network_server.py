"""Contract tests for NetworkServer (Scenarios 1, 2, 5, 6).

RED state: all tests must fail until implementation exists.
"""

import asyncio
import json
import time
import pytest

# These imports will fail until implementation exists (RED state)
# from clawd_tank_daemon.network_server import NetworkServer


# --- Helpers ---

def make_server(port=0, on_message=None, on_client_change=None, on_client_disconnect=None):
    """Create a NetworkServer on a random free port."""
    from clawd_tank_daemon.network_server import NetworkServer
    return NetworkServer(
        port=port,
        on_message=on_message or (lambda hostname, msg: None),
        on_client_change=on_client_change or (lambda clients: None),
        on_client_disconnect=on_client_disconnect or (lambda hostname: None),
    )


async def connect_and_hello(port, hostname="test-client"):
    """Helper: connect to server and perform hello handshake."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    hello = json.dumps({"type": "hello", "hostname": hostname}) + "\n"
    writer.write(hello.encode())
    await writer.drain()
    welcome_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
    welcome = json.loads(welcome_line.decode())
    return reader, writer, welcome


# ============================================================
# Scenario 1 — Server TCP Listener Start
# ============================================================

# Trace: Scenario 1, Section 3c — server starts listening
@pytest.mark.asyncio
async def test_network_server_start_listens_on_port():
    """Server must accept TCP connections after start()."""
    server = make_server(port=0)  # OS-assigned port
    await server.start()
    try:
        port = server.port
        assert port > 0
        # Verify we can open a TCP connection
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


# Trace: Scenario 1, Section 5 — port already in use
@pytest.mark.asyncio
async def test_network_server_start_port_in_use():
    """Server must handle port-in-use gracefully (not crash)."""
    server1 = make_server(port=0)
    await server1.start()
    port = server1.port
    try:
        server2 = make_server(port=port)
        with pytest.raises(OSError):
            await server2.start()
    finally:
        await server1.stop()


# Trace: Scenario 1, Section 4 — daemon stores server reference
@pytest.mark.asyncio
async def test_daemon_start_network_server_stores_ref():
    """Daemon must store NetworkServer reference after start."""
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


# ============================================================
# Scenario 2 — Client Hello Handshake
# ============================================================

# Trace: Scenario 2, Section 3a+3b — successful handshake
@pytest.mark.asyncio
async def test_handshake_hello_welcome():
    """Client hello must receive welcome with server hostname."""
    server = make_server(port=0)
    await server.start()
    try:
        _, writer, welcome = await connect_and_hello(server.port, "macbook-b")
        assert welcome["type"] == "welcome"
        assert "server" in welcome
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


# Trace: Scenario 2, Section 5 — missing hostname
@pytest.mark.asyncio
async def test_handshake_missing_hostname_rejected():
    """Hello without hostname must be rejected (connection closed)."""
    server = make_server(port=0)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        bad_hello = json.dumps({"type": "hello"}) + "\n"  # no hostname
        writer.write(bad_hello.encode())
        await writer.drain()
        # Server should close the connection
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert data == b""  # EOF = connection closed
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


# Trace: Scenario 2, Section 5 — handshake timeout
@pytest.mark.asyncio
async def test_handshake_timeout():
    """Server must close connection if no hello within timeout."""
    server = make_server(port=0)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        # Send nothing, wait for server to close
        data = await asyncio.wait_for(reader.read(1024), timeout=10.0)
        assert data == b""  # EOF
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


# Trace: Scenario 2, Section 5 — duplicate hostname replaces
@pytest.mark.asyncio
async def test_handshake_duplicate_hostname_replaces():
    """Second connection with same hostname must replace the first."""
    server = make_server(port=0)
    await server.start()
    try:
        _, writer1, _ = await connect_and_hello(server.port, "macbook-b")
        _, writer2, _ = await connect_and_hello(server.port, "macbook-b")
        await asyncio.sleep(0.1)  # Let server process
        assert len(server.get_client_list()) == 1
        assert "macbook-b" in server.get_client_list()
        writer1.close()
        writer2.close()
    finally:
        await server.stop()


# Trace: Scenario 2, Section 4 — client list updated
@pytest.mark.asyncio
async def test_client_list_updated_after_connect():
    """get_client_list() must include connected hostname."""
    clients_received = []
    server = make_server(port=0, on_client_change=lambda c: clients_received.append(list(c)))
    await server.start()
    try:
        _, writer, _ = await connect_and_hello(server.port, "macbook-b")
        await asyncio.sleep(0.1)
        assert "macbook-b" in server.get_client_list()
        assert any("macbook-b" in cl for cl in clients_received)
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


# Trace: Scenario 2, Section 5 — client reconnect
@pytest.mark.asyncio
async def test_client_reconnect_on_refused():
    """NetworkClient must retry connection on refusal."""
    from clawd_tank_daemon.network_client import NetworkClient
    connected = asyncio.Event()
    client = NetworkClient(
        host="127.0.0.1",
        port=19999,  # nothing listening
        on_connect_cb=lambda: connected.set(),
        on_disconnect_cb=lambda: None,
    )
    # Start connect in background — should retry without crashing
    task = asyncio.create_task(client.connect())
    await asyncio.sleep(1.0)  # Let it attempt + fail
    assert not client.is_connected
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ============================================================
# Scenario 3 — Remote Session Event Processing
# ============================================================

# Trace: Scenario 3, Section 3b — session ID scoping
@pytest.mark.asyncio
async def test_remote_session_id_scoped():
    """Remote session_id must be prefixed with hostname."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon._handle_remote_message("macbook-b", {
        "event": "session_start", "session_id": "s1", "project": "proj"
    })
    assert "macbook-b:s1" in daemon._session_states
    assert "s1" not in daemon._session_states


# Trace: Scenario 3, Section 3b — project badging
@pytest.mark.asyncio
async def test_remote_project_badged():
    """Remote project field must have [hostname] prefix."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    received_msgs = []
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon._handle_remote_message("macbook-b", {
        "event": "add", "hook": "Stop",
        "session_id": "s1", "project": "clawd-tank", "message": "hi"
    })
    notif = daemon._active_notifications.get("macbook-b:s1")
    assert notif is not None
    # Label is auto-assigned: first client gets "A"
    assert notif["project"] == "[A] clawd-tank"


# Trace: Scenario 3, Section 3d — remote in display state
@pytest.mark.asyncio
async def test_remote_session_in_display_state():
    """Remote working session must appear in display state anims."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon._handle_remote_message("macbook-b", {
        "event": "tool_use", "session_id": "s1", "tool_name": "Edit", "project": "proj"
    })
    state = daemon._compute_display_state()
    assert "anims" in state
    assert "typing" in state["anims"]


# Trace: Scenario 3, Section 3d — mixed local + remote
@pytest.mark.asyncio
async def test_remote_and_local_sessions_mixed():
    """Display state must include both local and remote sessions."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    # Local session
    await daemon._handle_message({
        "event": "tool_use", "session_id": "local-1", "tool_name": "Bash", "project": "proj"
    })
    # Remote session
    await daemon._handle_remote_message("macbook-b", {
        "event": "tool_use", "session_id": "remote-1", "tool_name": "Edit", "project": "proj"
    })
    state = daemon._compute_display_state()
    assert len(state["anims"]) == 2


# Trace: Scenario 3, Section 5 — malformed JSON skipped
@pytest.mark.asyncio
async def test_remote_malformed_json_skipped():
    """Server must skip malformed messages without crashing."""
    messages_received = []

    async def on_msg(hostname, msg):
        messages_received.append(msg)

    server = make_server(port=0, on_message=on_msg)
    await server.start()
    try:
        _, writer, _ = await connect_and_hello(server.port, "macbook-b")
        # Send malformed JSON
        writer.write(b"not json\n")
        await writer.drain()
        # Send valid message after
        valid = json.dumps({"event": "session_start", "session_id": "s1"}) + "\n"
        writer.write(valid.encode())
        await writer.drain()
        await asyncio.sleep(0.2)
        # Valid message should have been processed
        assert len(messages_received) >= 1
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


# Trace: Scenario 3, Section 4 — remote session persisted
@pytest.mark.asyncio
async def test_remote_session_persisted(tmp_path):
    """Remote sessions must be saved to sessions.json."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    sessions_path = tmp_path / "sessions.json"
    daemon = ClawdDaemon(sim_only=True, sessions_path=sessions_path)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon._handle_remote_message("macbook-b", {
        "event": "session_start", "session_id": "s1", "project": "proj"
    })
    assert sessions_path.exists()
    data = json.loads(sessions_path.read_text())
    assert "macbook-b:s1" in data.get("sessions", {})


# ============================================================
# Scenario 5 — Client Disconnect Session Cleanup
# ============================================================

# Trace: Scenario 5, Section 3b — remove all client sessions
@pytest.mark.asyncio
async def test_disconnect_removes_all_client_sessions():
    """All sessions with hostname prefix must be removed on disconnect."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    # Add two remote sessions
    await daemon._handle_remote_message("macbook-b", {
        "event": "session_start", "session_id": "s1", "project": "p"
    })
    await daemon._handle_remote_message("macbook-b", {
        "event": "session_start", "session_id": "s2", "project": "p"
    })
    assert "macbook-b:s1" in daemon._session_states
    assert "macbook-b:s2" in daemon._session_states

    daemon._handle_client_disconnect("macbook-b")
    assert "macbook-b:s1" not in daemon._session_states
    assert "macbook-b:s2" not in daemon._session_states


# Trace: Scenario 5, Section 3b — preserve local sessions
@pytest.mark.asyncio
async def test_disconnect_preserves_local_sessions():
    """Local sessions must not be affected by remote client disconnect."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon._handle_message({
        "event": "session_start", "session_id": "local-1", "project": "p"
    })
    await daemon._handle_remote_message("macbook-b", {
        "event": "session_start", "session_id": "s1", "project": "p"
    })

    daemon._handle_client_disconnect("macbook-b")
    assert "local-1" in daemon._session_states
    assert "macbook-b:s1" not in daemon._session_states


# Trace: Scenario 5, Section 4 — display state updated
@pytest.mark.asyncio
async def test_disconnect_updates_display_state():
    """Display state must reflect removed sessions after disconnect."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon._handle_remote_message("macbook-b", {
        "event": "tool_use", "session_id": "s1", "tool_name": "Edit", "project": "p"
    })
    assert "anims" in daemon._compute_display_state()

    daemon._handle_client_disconnect("macbook-b")
    assert daemon._compute_display_state() == {"status": "sleeping"}


# Trace: Scenario 5, Section 4 — notifications cleared
@pytest.mark.asyncio
async def test_disconnect_clears_client_notifications():
    """Active notifications from disconnected client must be removed."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon._handle_remote_message("macbook-b", {
        "event": "add", "hook": "Stop",
        "session_id": "s1", "project": "p", "message": "waiting"
    })
    assert "macbook-b:s1" in daemon._active_notifications

    daemon._handle_client_disconnect("macbook-b")
    assert "macbook-b:s1" not in daemon._active_notifications


# Trace: Scenario 5, Section 5 — no sessions is no-op
@pytest.mark.asyncio
async def test_disconnect_no_sessions_noop():
    """Disconnecting hostname with no sessions must not crash."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    # Should not raise
    daemon._handle_client_disconnect("unknown-host")


# ============================================================
# Scenario 6 — Hostname Badge on Notification Card
# ============================================================

# Trace: Scenario 6, Section 3a — badge format
@pytest.mark.asyncio
async def test_badge_format_bracket_hostname():
    """Badge must use [hostname] prefix format."""
    from clawd_tank_daemon.daemon import ClawdDaemon
    daemon = ClawdDaemon(sim_only=True)
    daemon._transports.clear()
    daemon._transport_queues.clear()

    await daemon._handle_remote_message("my-mac", {
        "event": "add", "hook": "Stop",
        "session_id": "s1", "project": "my-proj", "message": "hi"
    })
    notif = daemon._active_notifications["my-mac:s1"]
    # Auto-assigned label, format is [X]
    assert notif["project"].startswith("[")
    assert "] my-proj" in notif["project"]


# Trace: Scenario 6, Section 3b — BLE payload contains badge
@pytest.mark.asyncio
async def test_remote_notification_in_ble_payload():
    """BLE payload for remote add must include badged project."""
    from clawd_tank_daemon.protocol import daemon_message_to_ble_payload

    msg = {
        "event": "add", "session_id": "macbook-b:s1",
        "project": "[A] clawd-tank", "message": "Waiting"
    }
    payload_str = daemon_message_to_ble_payload(msg)
    payload = json.loads(payload_str)
    assert payload["project"] == "[A] clawd-tank"
    assert payload["id"] == "macbook-b:s1"
