"""Tests for daemon session state tracking and display state computation."""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from clawd_tank_daemon.daemon import ClawdDaemon


def make_daemon():
    """Create a daemon in sim-only mode with no actual transport."""
    d = ClawdDaemon(sim_only=True)
    d._transports.clear()
    d._transport_queues.clear()
    return d


def test_no_sessions_returns_sleeping():
    d = make_daemon()
    assert d._compute_display_state() == "sleeping"

def test_single_registered_session_returns_idle():
    d = make_daemon()
    d._session_states["s1"] = {"state": "registered", "last_event": time.time()}
    assert d._compute_display_state() == "idle"

def test_single_idle_session_returns_idle():
    d = make_daemon()
    d._session_states["s1"] = {"state": "idle", "last_event": time.time()}
    assert d._compute_display_state() == "idle"

def test_single_thinking_session_returns_thinking():
    d = make_daemon()
    d._session_states["s1"] = {"state": "thinking", "last_event": time.time()}
    assert d._compute_display_state() == "thinking"

def test_single_working_session_returns_working_1():
    d = make_daemon()
    d._session_states["s1"] = {"state": "working", "last_event": time.time()}
    assert d._compute_display_state() == "working_1"

def test_two_working_sessions_returns_working_2():
    d = make_daemon()
    d._session_states["s1"] = {"state": "working", "last_event": time.time()}
    d._session_states["s2"] = {"state": "working", "last_event": time.time()}
    assert d._compute_display_state() == "working_2"

def test_three_plus_working_sessions_returns_working_3():
    d = make_daemon()
    for i in range(5):
        d._session_states[f"s{i}"] = {"state": "working", "last_event": time.time()}
    assert d._compute_display_state() == "working_3"

def test_working_beats_thinking():
    d = make_daemon()
    d._session_states["s1"] = {"state": "working", "last_event": time.time()}
    d._session_states["s2"] = {"state": "thinking", "last_event": time.time()}
    assert d._compute_display_state() == "working_1"

def test_thinking_beats_confused():
    d = make_daemon()
    d._session_states["s1"] = {"state": "thinking", "last_event": time.time()}
    d._session_states["s2"] = {"state": "confused", "last_event": time.time()}
    assert d._compute_display_state() == "thinking"

def test_confused_beats_idle():
    d = make_daemon()
    d._session_states["s1"] = {"state": "confused", "last_event": time.time()}
    d._session_states["s2"] = {"state": "idle", "last_event": time.time()}
    assert d._compute_display_state() == "confused"

def test_registered_treated_as_idle():
    d = make_daemon()
    d._session_states["s1"] = {"state": "registered", "last_event": time.time()}
    d._session_states["s2"] = {"state": "confused", "last_event": time.time()}
    assert d._compute_display_state() == "confused"


# --- Task 4: _handle_message wiring ---

@pytest.mark.asyncio
async def test_session_start_registers_session():
    d = make_daemon()
    await d._handle_message({"event": "session_start", "session_id": "s1"})
    assert "s1" in d._session_states
    assert d._session_states["s1"]["state"] == "registered"

@pytest.mark.asyncio
async def test_prompt_submit_sets_thinking():
    d = make_daemon()
    d._session_states["s1"] = {"state": "idle", "last_event": time.time()}
    await d._handle_message({"event": "dismiss", "hook": "UserPromptSubmit", "session_id": "s1"})
    assert d._session_states["s1"]["state"] == "thinking"

@pytest.mark.asyncio
async def test_tool_use_sets_working():
    d = make_daemon()
    d._session_states["s1"] = {"state": "thinking", "last_event": time.time()}
    await d._handle_message({"event": "tool_use", "session_id": "s1"})
    assert d._session_states["s1"]["state"] == "working"

@pytest.mark.asyncio
async def test_stop_add_sets_idle():
    d = make_daemon()
    d._session_states["s1"] = {"state": "working", "last_event": time.time()}
    await d._handle_message({
        "event": "add", "hook": "Stop", "session_id": "s1",
        "project": "proj", "message": "Waiting",
    })
    assert d._session_states["s1"]["state"] == "idle"

@pytest.mark.asyncio
async def test_notification_add_sets_confused():
    d = make_daemon()
    d._session_states["s1"] = {"state": "idle", "last_event": time.time()}
    await d._handle_message({
        "event": "add", "hook": "Notification", "session_id": "s1",
        "project": "proj", "message": "Waiting",
    })
    assert d._session_states["s1"]["state"] == "confused"

@pytest.mark.asyncio
async def test_session_end_removes_session():
    d = make_daemon()
    d._session_states["s1"] = {"state": "idle", "last_event": time.time()}
    await d._handle_message({"event": "dismiss", "hook": "SessionEnd", "session_id": "s1"})
    assert "s1" not in d._session_states

@pytest.mark.asyncio
async def test_implicit_session_creation():
    d = make_daemon()
    await d._handle_message({"event": "tool_use", "session_id": "s1"})
    assert "s1" in d._session_states
    assert d._session_states["s1"]["state"] == "working"

@pytest.mark.asyncio
async def test_last_display_state_tracks_changes():
    d = make_daemon()
    assert d._last_display_state == "sleeping"
    await d._handle_message({"event": "session_start", "session_id": "s1"})
    assert d._last_display_state == "idle"
    await d._handle_message({"event": "dismiss", "hook": "UserPromptSubmit", "session_id": "s1"})
    assert d._last_display_state == "thinking"
    await d._handle_message({"event": "tool_use", "session_id": "s1"})
    assert d._last_display_state == "working_1"
    await d._handle_message({
        "event": "add", "hook": "Stop", "session_id": "s1",
        "project": "proj", "message": "Waiting",
    })
    assert d._last_display_state == "idle"
    await d._handle_message({"event": "dismiss", "hook": "SessionEnd", "session_id": "s1"})
    assert d._last_display_state == "sleeping"
