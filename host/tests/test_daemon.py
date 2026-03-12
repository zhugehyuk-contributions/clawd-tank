import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from clawd_tank_daemon.daemon import ClawdDaemon


@pytest.mark.asyncio
async def test_handle_add_tracks_notification():
    daemon = ClawdDaemon()
    msg = {"event": "add", "session_id": "s1", "project": "proj", "message": "hi"}
    await daemon._handle_message(msg)
    assert "s1" in daemon._active_notifications
    assert daemon._pending_queue.qsize() == 1


@pytest.mark.asyncio
async def test_handle_dismiss_removes_notification():
    daemon = ClawdDaemon()
    await daemon._handle_message(
        {"event": "add", "session_id": "s1", "project": "p", "message": "m"}
    )
    await daemon._handle_message({"event": "dismiss", "session_id": "s1"})
    assert "s1" not in daemon._active_notifications
    assert daemon._pending_queue.qsize() == 2


@pytest.mark.asyncio
async def test_dismiss_unknown_is_safe():
    daemon = ClawdDaemon()
    await daemon._handle_message({"event": "dismiss", "session_id": "nope"})
    assert daemon._pending_queue.qsize() == 1


# --- Edge cases ---

@pytest.mark.asyncio
async def test_duplicate_add_updates_not_duplicates():
    """Adding the same session_id twice must update the entry, not create two."""
    daemon = ClawdDaemon()
    await daemon._handle_message(
        {"event": "add", "session_id": "s1", "project": "p", "message": "first"}
    )
    await daemon._handle_message(
        {"event": "add", "session_id": "s1", "project": "p", "message": "updated"}
    )
    assert len(daemon._active_notifications) == 1
    assert daemon._active_notifications["s1"]["message"] == "updated"
    # Both adds go to the queue for BLE delivery
    assert daemon._pending_queue.qsize() == 2


@pytest.mark.asyncio
async def test_empty_session_id_add_and_dismiss():
    """Empty-string session_id must be tracked and dismissable."""
    daemon = ClawdDaemon()
    await daemon._handle_message(
        {"event": "add", "session_id": "", "project": "p", "message": "m"}
    )
    assert "" in daemon._active_notifications

    await daemon._handle_message({"event": "dismiss", "session_id": ""})
    assert "" not in daemon._active_notifications


@pytest.mark.asyncio
async def test_multiple_sessions_independent():
    """Multiple independent session IDs must not interfere with each other."""
    daemon = ClawdDaemon()
    for sid in ("s1", "s2", "s3"):
        await daemon._handle_message(
            {"event": "add", "session_id": sid, "project": "p", "message": "m"}
        )
    assert len(daemon._active_notifications) == 3

    await daemon._handle_message({"event": "dismiss", "session_id": "s2"})
    assert len(daemon._active_notifications) == 2
    assert "s1" in daemon._active_notifications
    assert "s2" not in daemon._active_notifications
    assert "s3" in daemon._active_notifications


@pytest.mark.asyncio
async def test_unknown_event_does_not_crash_sender():
    """An unknown event in the queue must be logged and skipped, not crash _ble_sender."""
    daemon = ClawdDaemon()
    await daemon._handle_message({"event": "bogus", "session_id": "x"})
    await daemon._handle_message({"event": "dismiss", "session_id": "x"})

    from clawd_tank_daemon.protocol import daemon_message_to_ble_payload
    with pytest.raises(ValueError):
        daemon_message_to_ble_payload({"event": "bogus"})

    assert daemon._pending_queue.qsize() == 2


@pytest.mark.asyncio
async def test_ble_sender_skips_unknown_event():
    """_ble_sender must skip unknown events and continue processing the queue."""
    daemon = ClawdDaemon()
    daemon._ble = AsyncMock()
    daemon._ble.ensure_connected = AsyncMock()
    daemon._ble.write_notification = AsyncMock(return_value=True)

    await daemon._pending_queue.put({"event": "bogus", "session_id": "x"})
    await daemon._pending_queue.put({"event": "dismiss", "session_id": "d1"})

    sender = asyncio.create_task(daemon._ble_sender())
    await asyncio.sleep(0.1)
    daemon._running = False
    sender.cancel()
    try:
        await sender
    except asyncio.CancelledError:
        pass

    assert daemon._ble.write_notification.call_count >= 1


# --- _replay_active ---

@pytest.mark.asyncio
async def test_replay_active_sends_all_active_notifications():
    """_replay_active must write every currently active notification over BLE."""
    daemon = ClawdDaemon()
    daemon._ble = AsyncMock()
    daemon._ble.write_notification = AsyncMock(return_value=True)

    # Populate active notifications directly (bypassing the queue)
    daemon._active_notifications = {
        "s1": {"event": "add", "session_id": "s1", "project": "p1", "message": "m1"},
        "s2": {"event": "add", "session_id": "s2", "project": "p2", "message": "m2"},
        "s3": {"event": "add", "session_id": "s3", "project": "p3", "message": "m3"},
    }

    await daemon._replay_active()

    # All three active notifications should have been sent
    assert daemon._ble.write_notification.call_count == 3
    # Verify BLE payloads contain the right session IDs
    written_args = [call.args[0] for call in daemon._ble.write_notification.call_args_list]
    import json
    written_ids = {json.loads(p)["id"] for p in written_args}
    assert written_ids == {"s1", "s2", "s3"}


@pytest.mark.asyncio
async def test_replay_active_empty_store_sends_nothing():
    """_replay_active with no active notifications must not call write_notification."""
    daemon = ClawdDaemon()
    daemon._ble = AsyncMock()
    daemon._ble.write_notification = AsyncMock(return_value=True)

    await daemon._replay_active()

    daemon._ble.write_notification.assert_not_called()


@pytest.mark.asyncio
async def test_replay_active_skips_unknown_events():
    """_replay_active must skip entries with unknown events rather than crashing."""
    daemon = ClawdDaemon()
    daemon._ble = AsyncMock()
    daemon._ble.write_notification = AsyncMock(return_value=True)

    daemon._active_notifications = {
        "s1": {"event": "add", "session_id": "s1", "project": "p", "message": "m"},
        "bad": {"event": "bogus", "session_id": "bad"},
    }

    # Should not raise — bad entry is skipped, valid one is sent
    await daemon._replay_active()
    assert daemon._ble.write_notification.call_count == 1


@pytest.mark.asyncio
async def test_replay_active_concurrent_mutation_is_safe():
    """_replay_active snapshots active notifications so concurrent mutation doesn't crash."""
    daemon = ClawdDaemon()
    daemon._ble = AsyncMock()

    write_calls = []

    async def slow_write(payload):
        write_calls.append(payload)
        # Simulate a slow BLE write; concurrent task mutates _active_notifications
        await asyncio.sleep(0.01)
        return True

    daemon._ble.write_notification = slow_write

    daemon._active_notifications = {
        "s1": {"event": "add", "session_id": "s1", "project": "p", "message": "m"},
        "s2": {"event": "add", "session_id": "s2", "project": "p", "message": "m"},
    }

    async def mutate():
        # Remove s2 and add s3 while replay is in progress
        await asyncio.sleep(0.005)
        daemon._active_notifications.pop("s2", None)
        daemon._active_notifications["s3"] = {
            "event": "add", "session_id": "s3", "project": "p", "message": "m"
        }

    # Run replay and mutation concurrently
    await asyncio.gather(daemon._replay_active(), mutate())

    # Replay used a snapshot so it sent s1 and s2 (the state at snapshot time)
    import json
    replayed_ids = {json.loads(p)["id"] for p in write_calls}
    assert replayed_ids == {"s1", "s2"}


# --- BLE write failure → reconnect → replay ---

@pytest.mark.asyncio
async def test_ble_write_failure_triggers_reconnect_and_replay():
    """When write_notification returns False, _ble_sender reconnects and replays active notifications."""
    daemon = ClawdDaemon()
    daemon._ble = AsyncMock()
    daemon._ble.is_connected = True

    # First write fails; subsequent writes (from replay) succeed
    write_results = [False, True, True]
    write_calls = []

    async def mock_write(payload):
        write_calls.append(payload)
        return write_results.pop(0) if write_results else True

    daemon._ble.write_notification = mock_write
    daemon._ble.ensure_connected = AsyncMock()

    # Pre-populate one active notification for replay
    daemon._active_notifications = {
        "s1": {"event": "add", "session_id": "s1", "project": "p", "message": "m"},
    }

    # Enqueue the message that will fail on first write
    await daemon._pending_queue.put(
        {"event": "add", "session_id": "s2", "project": "p", "message": "m"}
    )

    sender = asyncio.create_task(daemon._ble_sender())
    await asyncio.sleep(0.2)
    daemon._running = False
    sender.cancel()
    try:
        await sender
    except asyncio.CancelledError:
        pass

    # ensure_connected must have been called at least twice (initial + reconnect)
    assert daemon._ble.ensure_connected.call_count >= 2
    # write_notification called: once for the failing write, once for replay of s1
    assert len(write_calls) >= 2


@pytest.mark.asyncio
async def test_ble_write_failure_replays_multiple_active():
    """After a BLE write failure, all active notifications are replayed in order."""
    daemon = ClawdDaemon()
    daemon._ble = AsyncMock()
    daemon._ble.is_connected = True

    write_calls = []
    call_count = [0]

    async def mock_write(payload):
        call_count[0] += 1
        write_calls.append(payload)
        # Fail only on the very first write
        if call_count[0] == 1:
            return False
        return True

    daemon._ble.write_notification = mock_write
    daemon._ble.ensure_connected = AsyncMock()

    daemon._active_notifications = {
        "s1": {"event": "add", "session_id": "s1", "project": "p", "message": "m1"},
        "s2": {"event": "add", "session_id": "s2", "project": "p", "message": "m2"},
    }

    await daemon._pending_queue.put(
        {"event": "dismiss", "session_id": "s_gone"}
    )

    sender = asyncio.create_task(daemon._ble_sender())
    await asyncio.sleep(0.3)
    daemon._running = False
    sender.cancel()
    try:
        await sender
    except asyncio.CancelledError:
        pass

    import json
    # First call was the failing dismiss; subsequent calls are the replay writes
    replayed_ids = {json.loads(p).get("id") for p in write_calls[1:] if json.loads(p).get("id")}
    assert "s1" in replayed_ids
    assert "s2" in replayed_ids
