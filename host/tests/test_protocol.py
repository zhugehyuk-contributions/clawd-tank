import json
from clawd_daemon.protocol import (
    hook_payload_to_daemon_message,
    daemon_message_to_ble_payload,
)


def test_idle_prompt_to_add():
    hook = {
        "hook_event_name": "Notification",
        "notification_type": "idle_prompt",
        "session_id": "abc-123",
        "cwd": "/Users/me/Projects/my-project",
        "message": "Claude is waiting for input",
    }
    msg = hook_payload_to_daemon_message(hook)
    assert msg is not None
    assert msg["event"] == "add"
    assert msg["session_id"] == "abc-123"
    assert msg["project"] == "my-project"
    assert msg["message"] == "Claude is waiting for input"


def test_prompt_submit_to_dismiss():
    hook = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "abc-123",
        "cwd": "/Users/me/Projects/my-project",
    }
    msg = hook_payload_to_daemon_message(hook)
    assert msg is not None
    assert msg["event"] == "dismiss"
    assert msg["session_id"] == "abc-123"


def test_session_end_to_dismiss():
    hook = {
        "hook_event_name": "SessionEnd",
        "session_id": "abc-123",
        "cwd": "/Users/me/Projects/foo",
    }
    msg = hook_payload_to_daemon_message(hook)
    assert msg is not None
    assert msg["event"] == "dismiss"
    assert msg["session_id"] == "abc-123"


def test_irrelevant_notification_ignored():
    hook = {
        "hook_event_name": "Notification",
        "notification_type": "auth_success",
        "session_id": "abc-123",
        "cwd": "/tmp",
    }
    msg = hook_payload_to_daemon_message(hook)
    assert msg is None


def test_daemon_add_to_ble():
    msg = {"event": "add", "session_id": "s1", "project": "proj", "message": "hi"}
    ble = daemon_message_to_ble_payload(msg)
    parsed = json.loads(ble)
    assert parsed["action"] == "add"
    assert parsed["id"] == "s1"
    assert parsed["project"] == "proj"
    assert parsed["message"] == "hi"


def test_daemon_dismiss_to_ble():
    msg = {"event": "dismiss", "session_id": "s1"}
    ble = daemon_message_to_ble_payload(msg)
    parsed = json.loads(ble)
    assert parsed["action"] == "dismiss"
    assert parsed["id"] == "s1"
