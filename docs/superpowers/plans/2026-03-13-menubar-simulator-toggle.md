# Menubar Simulator Toggle Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a checkable menu item to the macOS status bar app that enables/disables the simulator TCP transport at runtime, with per-transport connection status and persisted preferences.

**Architecture:** The daemon gains `add_transport`/`remove_transport` methods for dynamic transport lifecycle. The observer callback gets a `transport` parameter for per-transport status. The menubar app adds a toggle that creates/destroys a `SimClient` at runtime, with state persisted in `~/.clawd-tank/preferences.json`.

**Tech Stack:** Python 3.10+ (asyncio, rumps, json)

**Spec:** `docs/superpowers/specs/2026-03-13-menubar-simulator-toggle-design.md`

---

## Chunk 1: Daemon internals

### Task 1: Add `_sender_tasks` dict and initial replay in `_transport_sender`

**Files:**
- Modify: `host/clawd_tank_daemon/daemon.py:87-120` (`__init__`), `179-210` (`_transport_sender`), `257-286` (`run`), `220-234` (`_shutdown`)
- Modify: `host/tests/test_daemon.py`

- [ ] **Step 1: Write failing test for initial replay after connect**

In `host/tests/test_daemon.py`, add a test that verifies `_transport_sender` replays active notifications after initial connect:

```python
@pytest.mark.asyncio
async def test_transport_sender_replays_active_on_initial_connect():
    """Sender replays active notifications after initial connect + sync_time."""
    daemon = ClawdDaemon()
    daemon._active_notifications = {
        "s1": {"event": "add", "session_id": "s1", "project": "p", "message": "m1"},
    }

    mock_transport = AsyncMock()
    mock_transport.is_connected = True
    mock_transport.ensure_connected = AsyncMock()
    mock_transport.write_notification = AsyncMock(return_value=True)
    daemon._transports["ble"] = mock_transport

    sender = asyncio.create_task(daemon._transport_sender("ble"))
    await asyncio.sleep(0.3)
    daemon._running = False
    sender.cancel()
    try:
        await sender
    except asyncio.CancelledError:
        pass

    # Calls: sync_time, then replay (1 notification)
    write_calls = mock_transport.write_notification.call_args_list
    assert len(write_calls) >= 2
    # Second call should be the replayed notification
    replayed = json.loads(write_calls[1][0][0])
    assert replayed["action"] == "add"
    assert replayed["id"]  # has an id field
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest tests/test_daemon.py::test_transport_sender_replays_active_on_initial_connect -v`
Expected: FAIL — sender does not replay after initial connect

- [ ] **Step 3: Add `_sender_tasks` dict and initial replay**

In `host/clawd_tank_daemon/daemon.py`:

In `__init__` (after `self._transport_queues` initialization around line 105), add:

```python
self._sender_tasks: dict[str, asyncio.Task] = {}
```

In `_transport_sender` (after the `_sync_time_for` call around line 186), add:

```python
await self._replay_active_for(transport)
```

In `run()` (around line 274 where tasks are created), change the local `tasks` list to use `self._sender_tasks`:

```python
for name in self._transports:
    self._sender_tasks[name] = asyncio.create_task(self._transport_sender(name))
```

Remove the local `tasks` list and the post-`shutdown_event` cancellation loop from `run()` — `_shutdown()` now handles all task cancellation.

In `_shutdown()`, add task cancellation before disconnect (around line 222):

```python
for task in self._sender_tasks.values():
    task.cancel()
for task in self._sender_tasks.values():
    try:
        await task
    except asyncio.CancelledError:
        pass
self._sender_tasks.clear()
```

- [ ] **Step 4: Fix existing tests that break due to initial replay**

The `test_ble_write_failure_triggers_reconnect_and_replay` and `test_ble_write_failure_replays_multiple_active` tests will need their `write_results` adjusted since the sender now does an extra replay on initial connect. Update the fail thresholds accordingly (the sync_time write + replay writes now happen before the queue message).

- [ ] **Step 5: Run all daemon tests**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest tests/test_daemon.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add host/clawd_tank_daemon/daemon.py host/tests/test_daemon.py
git commit -m "feat(daemon): add _sender_tasks dict and initial replay in transport sender"
```

### Task 2: Update observer callback with transport parameter

**Files:**
- Modify: `host/clawd_tank_daemon/daemon.py:26-29` (`DaemonObserver`), `140-151` (`_on_transport_connect`, `_on_transport_disconnect`)
- Modify: `host/clawd_tank_menubar/app.py:117-123` (`on_connection_change`)
- Modify: `host/tests/test_menubar.py:19-20` (`FakeObserver`)
- Modify: `host/tests/test_observer.py:9-10` (`MockObserver`)

- [ ] **Step 1: Write failing test for transport parameter in observer**

In `host/tests/test_menubar.py`, update `FakeObserver` and add a test:

```python
class FakeObserver:
    def __init__(self):
        self.connection_changes = []
        self.notification_changes = []

    def on_connection_change(self, connected: bool, transport: str = "") -> None:
        self.connection_changes.append((connected, transport))

    def on_notification_change(self, count: int) -> None:
        self.notification_changes.append(count)


@pytest.mark.asyncio
async def test_observer_receives_transport_name():
    obs = FakeObserver()
    daemon = ClawdDaemon(observer=obs)
    mock_transport = AsyncMock()
    mock_transport.is_connected = True
    daemon._transports["ble"] = mock_transport
    daemon._on_transport_connect("ble")
    assert obs.connection_changes == [(True, "ble")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest tests/test_menubar.py::test_observer_receives_transport_name -v`
Expected: FAIL — observer receives `True` but not `("ble",)` tuple, or `TypeError` from extra argument

- [ ] **Step 3: Update DaemonObserver Protocol and daemon methods**

In `host/clawd_tank_daemon/daemon.py`:

Update `DaemonObserver` (line 28):

```python
def on_connection_change(self, connected: bool, transport: str = "") -> None: ...
```

Update `_on_transport_connect` (line 144):

```python
self._observer.on_connection_change(True, name)
```

Update `_on_transport_disconnect` (line 150):

```python
self._observer.on_connection_change(any_connected, name)
```

- [ ] **Step 4: Update all observer implementations**

In `host/clawd_tank_menubar/app.py`, update `on_connection_change` (line 117):

```python
def on_connection_change(self, connected: bool, transport: str = "") -> None:
    self._connected = connected
    if connected and self._loop:
        asyncio.run_coroutine_threadsafe(
            self._read_device_config(), self._loop
        )
    self._schedule_menu_update()
```

In `host/tests/test_observer.py`, update `MockObserver` (line 9):

```python
def on_connection_change(self, connected: bool, transport: str = "") -> None:
    self.connection_changes.append(connected)
```

- [ ] **Step 5: Fix existing tests that check `connection_changes`**

In `host/tests/test_menubar.py`, update `test_disconnect_callback_fires_observer`:

```python
assert obs.connection_changes == [(False, "ble")]
```

Update `test_add_then_dismiss_observer_sequence` — notification_changes is unchanged (it only tests `on_notification_change`).

- [ ] **Step 6: Run all tests**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add host/clawd_tank_daemon/daemon.py host/clawd_tank_menubar/app.py host/tests/test_menubar.py host/tests/test_observer.py
git commit -m "feat(daemon): add transport parameter to observer connection callback"
```

---

## Chunk 2: Dynamic transport API

### Task 3: Implement `add_transport` and `remove_transport`

**Files:**
- Modify: `host/clawd_tank_daemon/daemon.py` (new methods after `_shutdown`)
- Modify: `host/tests/test_daemon.py`

- [ ] **Step 1: Write failing test for `add_transport`**

```python
@pytest.mark.asyncio
async def test_add_transport_creates_queue_and_sender():
    """add_transport registers transport, creates queue, starts sender."""
    daemon = ClawdDaemon()

    mock_transport = AsyncMock()
    mock_transport.is_connected = True
    mock_transport.ensure_connected = AsyncMock()
    mock_transport.write_notification = AsyncMock(return_value=True)

    await daemon.add_transport("sim", mock_transport)

    assert "sim" in daemon._transports
    assert "sim" in daemon._transport_queues
    assert "sim" in daemon._sender_tasks
    assert not daemon._sender_tasks["sim"].done()

    # Clean up
    daemon._running = False
    daemon._sender_tasks["sim"].cancel()
    try:
        await daemon._sender_tasks["sim"]
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest tests/test_daemon.py::test_add_transport_creates_queue_and_sender -v`
Expected: FAIL — `add_transport` method not found

- [ ] **Step 3: Write failing test for `remove_transport`**

```python
@pytest.mark.asyncio
async def test_remove_transport_cancels_sender_and_disconnects():
    """remove_transport cancels sender task and disconnects client."""
    daemon = ClawdDaemon()

    mock_transport = AsyncMock()
    mock_transport.is_connected = True
    mock_transport.ensure_connected = AsyncMock()
    mock_transport.write_notification = AsyncMock(return_value=True)
    mock_transport.disconnect = AsyncMock()

    await daemon.add_transport("sim", mock_transport)
    assert "sim" in daemon._sender_tasks

    await daemon.remove_transport("sim")

    assert "sim" not in daemon._transports
    assert "sim" not in daemon._transport_queues
    assert "sim" not in daemon._sender_tasks
    mock_transport.disconnect.assert_awaited_once()
```

- [ ] **Step 4: Write failing test for `add_transport` wires callbacks**

```python
@pytest.mark.asyncio
async def test_add_transport_wires_callbacks():
    """add_transport sets connect/disconnect callbacks on the client."""
    daemon = ClawdDaemon()
    obs = FakeObserver()  # Use FakeObserver from test_menubar pattern
    daemon._observer = obs

    mock_transport = AsyncMock()
    mock_transport.is_connected = True
    mock_transport.ensure_connected = AsyncMock()
    mock_transport.write_notification = AsyncMock(return_value=True)
    mock_transport._on_connect_cb = None
    mock_transport._on_disconnect_cb = None

    await daemon.add_transport("sim", mock_transport)

    # Callbacks should be wired
    assert mock_transport._on_connect_cb is not None
    assert mock_transport._on_disconnect_cb is not None

    # Calling connect callback should notify observer
    mock_transport._on_connect_cb()
    assert len(obs.connection_changes) == 1
    assert obs.connection_changes[0] == (True, "sim")

    # Clean up
    daemon._running = False
    daemon._sender_tasks["sim"].cancel()
    try:
        await daemon._sender_tasks["sim"]
    except asyncio.CancelledError:
        pass
```

Import `FakeObserver` or duplicate the pattern at the top of `test_daemon.py`:

```python
class FakeObserver:
    def __init__(self):
        self.connection_changes = []
        self.notification_changes = []

    def on_connection_change(self, connected: bool, transport: str = "") -> None:
        self.connection_changes.append((connected, transport))

    def on_notification_change(self, count: int) -> None:
        self.notification_changes.append(count)
```

- [ ] **Step 5: Write failing test for `remove_transport` when sender is blocked in connect**

```python
@pytest.mark.asyncio
async def test_remove_transport_while_connecting():
    """remove_transport cancels sender even when blocked in connect retry loop."""
    daemon = ClawdDaemon()

    mock_transport = AsyncMock()
    mock_transport.is_connected = False
    # ensure_connected blocks indefinitely (simulates connect retry loop)
    mock_transport.ensure_connected = AsyncMock(side_effect=lambda: asyncio.sleep(999))
    mock_transport.write_notification = AsyncMock(return_value=True)
    mock_transport.disconnect = AsyncMock()

    await daemon.add_transport("sim", mock_transport)
    await asyncio.sleep(0.1)  # Let sender start and block in ensure_connected

    await daemon.remove_transport("sim")

    assert "sim" not in daemon._sender_tasks
    assert "sim" not in daemon._transports
```

- [ ] **Step 6: Write failing test for `_shutdown` with dynamically-added transport**

```python
@pytest.mark.asyncio
async def test_shutdown_cancels_dynamically_added_transport():
    """_shutdown cleans up sender tasks added via add_transport."""
    daemon = ClawdDaemon()

    mock_transport = AsyncMock()
    mock_transport.is_connected = True
    mock_transport.ensure_connected = AsyncMock()
    mock_transport.write_notification = AsyncMock(return_value=True)
    mock_transport.disconnect = AsyncMock()

    await daemon.add_transport("sim", mock_transport)
    assert "sim" in daemon._sender_tasks

    await daemon._shutdown()

    assert daemon._sender_tasks == {}
    mock_transport.disconnect.assert_awaited()
```

- [ ] **Step 7: Write failing test for broadcast to dynamically-added transport**

```python
@pytest.mark.asyncio
async def test_handle_message_broadcasts_to_dynamically_added_transport():
    """Messages broadcast to transports added via add_transport."""
    daemon = ClawdDaemon()

    mock_transport = AsyncMock()
    mock_transport.is_connected = True
    mock_transport.ensure_connected = AsyncMock()
    mock_transport.write_notification = AsyncMock(return_value=True)

    await daemon.add_transport("sim", mock_transport)

    await daemon._handle_message(
        {"event": "add", "session_id": "s1", "project": "p", "message": "m"}
    )

    assert daemon._transport_queues["sim"].qsize() == 1

    # Clean up
    daemon._running = False
    daemon._sender_tasks["sim"].cancel()
    try:
        await daemon._sender_tasks["sim"]
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 8: Implement `add_transport` and `remove_transport`**

In `host/clawd_tank_daemon/daemon.py`, add after `_shutdown` (around line 234):

```python
async def add_transport(self, name: str, client: TransportClient) -> None:
    """Add a transport dynamically and start its sender task."""
    client._on_connect_cb = lambda: self._on_transport_connect(name)
    client._on_disconnect_cb = lambda: self._on_transport_disconnect(name)
    self._transports[name] = client
    self._transport_queues[name] = asyncio.Queue()
    self._sender_tasks[name] = asyncio.create_task(self._transport_sender(name))

async def remove_transport(self, name: str) -> None:
    """Stop sender task, disconnect client, and remove transport."""
    if name in self._sender_tasks:
        self._sender_tasks[name].cancel()
        try:
            await self._sender_tasks[name]
        except asyncio.CancelledError:
            pass
        del self._sender_tasks[name]
    if name in self._transports:
        client = self._transports[name]
        if client.is_connected:
            await client.disconnect()
        del self._transports[name]
    self._transport_queues.pop(name, None)
    self._on_transport_disconnect(name)
```

- [ ] **Step 9: Run all tests**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest -v`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add host/clawd_tank_daemon/daemon.py host/tests/test_daemon.py
git commit -m "feat(daemon): add dynamic add_transport and remove_transport methods"
```

---

## Chunk 3: Menubar toggle and status display

### Task 4: Add preference persistence

**Files:**
- Create: `host/clawd_tank_menubar/preferences.py`
- Modify: `host/tests/test_menubar.py`

- [ ] **Step 1: Write failing tests for preference load/save**

In `host/tests/test_menubar.py`:

```python
import tempfile
from pathlib import Path
from clawd_tank_menubar.preferences import load_preferences, save_preferences

def test_load_preferences_missing_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        prefs = load_preferences(Path(tmpdir) / "prefs.json")
        assert prefs == {"sim_enabled": False}

def test_save_and_load_preferences():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "subdir" / "prefs.json"
        save_preferences(path, {"sim_enabled": True})
        prefs = load_preferences(path)
        assert prefs == {"sim_enabled": True}

def test_load_preferences_malformed_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "prefs.json"
        path.write_text("not json{{{")
        prefs = load_preferences(path)
        assert prefs == {"sim_enabled": False}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest tests/test_menubar.py::test_load_preferences_missing_file tests/test_menubar.py::test_save_and_load_preferences tests/test_menubar.py::test_load_preferences_malformed_json -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement preferences module**

Create `host/clawd_tank_menubar/preferences.py`:

```python
# host/clawd_tank_menubar/preferences.py
"""Persistent preferences for the Clawd Tank menubar app."""

import json
import logging
from pathlib import Path

logger = logging.getLogger("clawd-tank.menubar")

DEFAULTS = {"sim_enabled": False}
PREFS_PATH = Path.home() / ".clawd-tank" / "preferences.json"


def load_preferences(path: Path = PREFS_PATH) -> dict:
    """Load preferences from disk. Returns defaults if missing or malformed."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save_preferences(path: Path = PREFS_PATH, prefs: dict = None) -> None:
    """Save preferences to disk. Creates parent directory if needed."""
    if prefs is None:
        prefs = DEFAULTS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prefs, indent=2) + "\n")
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest tests/test_menubar.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add host/clawd_tank_menubar/preferences.py host/tests/test_menubar.py
git commit -m "feat(menubar): add preference persistence module"
```

### Task 5: Add per-transport status display and simulator toggle

**Files:**
- Modify: `host/clawd_tank_menubar/app.py`
- Modify: `host/tests/test_menubar.py`

- [ ] **Step 1: Write failing test for per-transport observer tracking**

In `host/tests/test_menubar.py`:

```python
@pytest.mark.asyncio
async def test_per_transport_status_tracking():
    """Observer tracks per-transport status when transport name is given."""
    obs = FakeObserver()
    daemon = ClawdDaemon(observer=obs)

    mock_ble = AsyncMock()
    mock_ble.is_connected = True
    daemon._transports["ble"] = mock_ble
    daemon._on_transport_connect("ble")

    mock_sim = AsyncMock()
    mock_sim.is_connected = True
    daemon._transports["sim"] = mock_sim
    daemon._on_transport_connect("sim")

    assert obs.connection_changes == [(True, "ble"), (True, "sim")]
```

- [ ] **Step 2: Run test to verify it passes** (this should already work from Task 2)

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest tests/test_menubar.py::test_per_transport_status_tracking -v`
Expected: PASS

- [ ] **Step 3: Update `ClawdTankApp` for per-transport status**

In `host/clawd_tank_menubar/app.py`:

Add import at top:

```python
from clawd_tank_daemon.sim_client import SimClient, SIM_DEFAULT_PORT
from .preferences import load_preferences, save_preferences, PREFS_PATH
```

In `__init__`:
- **Remove** `self._connected = False` (line 36)
- **Add** `self._transport_status: dict[str, bool] = {}`

Replace `_connected` with a computed property so that existing guards in `_on_brightness_change`, `_on_sleep_timeout_select`, etc. continue to work:

```python
@property
def _connected(self) -> bool:
    return any(self._transport_status.values()) if self._transport_status else False
```

In `on_connection_change` (Task 2), the old `self._connected = connected` line is gone — the property reads from `_transport_status` instead.

Replace the `_status_item` and `_subtitle_item` with per-transport status items:

```python
self._ble_status_item = rumps.MenuItem("BLE: Connecting...", callback=None)
self._ble_status_item.set_callback(None)
self._sim_status_item = rumps.MenuItem("", callback=None)
self._sim_status_item.set_callback(None)
```

Add the simulator toggle after sleep menu:

```python
self._sim_toggle = rumps.MenuItem("Enable Simulator", callback=self._on_toggle_simulator)
prefs = load_preferences()
self._sim_toggle.state = prefs.get("sim_enabled", False)
```

Update menu assembly to include the new items:

```python
self.menu = [
    self._ble_status_item,
    self._sim_status_item,
    None,
    self._brightness_item,
    None,
    self._sleep_menu,
    None,
    self._sim_toggle,
    None,
    self._login_item,
    None,
    self._reconnect_item,
    None,
    self._quit_item,
]
```

- [ ] **Step 4: Update `on_connection_change` for per-transport tracking**

```python
def on_connection_change(self, connected: bool, transport: str = "") -> None:
    if transport:
        self._transport_status[transport] = connected
    if connected and self._loop:
        asyncio.run_coroutine_threadsafe(
            self._read_device_config(), self._loop
        )
    self._schedule_menu_update()
```

- [ ] **Step 5: Update `_update_menu_state` for per-transport display**

Replace the existing status update logic with:

```python
TRANSPORT_NAMES = {"ble": "BLE", "sim": "Simulator"}

def _update_menu_state(self):
    """Update all menu items based on current state. Must run on main thread."""
    connected = self._connected

    # Per-transport status
    ble_connected = self._transport_status.get("ble", False)
    self._ble_status_item.title = f"BLE: {'Connected' if ble_connected else 'Connecting...'}"

    if "sim" in self._transport_status:
        sim_connected = self._transport_status.get("sim", False)
        self._sim_status_item.title = f"Simulator: {'Connected' if sim_connected else 'Connecting...'}"
    else:
        self._sim_status_item.title = ""

    if connected:
        if self._notification_count > 0:
            self.icon = self._icon_path("crab-notifications")
        else:
            self.icon = self._icon_path("crab-connected")

        brightness = self._current_config.get("brightness", 102)
        self._brightness_slider.set_value(brightness)
        self._brightness_slider.set_enabled(True)

        timeout = self._current_config.get("sleep_timeout", 300)
        self._sleep_timeout_value = timeout
        for key, item in self._sleep_menu.items():
            item.state = (item._seconds == timeout)

        self._reconnect_item.set_callback(self._on_reconnect)
    else:
        self.icon = self._icon_path("crab-disconnected")
        self._brightness_slider.set_enabled(False)
        self._reconnect_item.set_callback(None)
    self.title = ""
```

- [ ] **Step 6: Add toggle callback and startup sim init**

```python
def _on_toggle_simulator(self, sender):
    """Toggle the simulator transport on/off."""
    sender.state = not sender.state
    save_preferences(prefs={"sim_enabled": sender.state})

    if sender.state:
        self._transport_status["sim"] = False
        self._schedule_menu_update()
        if self._loop and self._daemon:
            client = SimClient(port=SIM_DEFAULT_PORT)
            asyncio.run_coroutine_threadsafe(
                self._daemon.add_transport("sim", client), self._loop
            )
    else:
        self._transport_status.pop("sim", None)
        self._schedule_menu_update()
        if self._loop and self._daemon:
            asyncio.run_coroutine_threadsafe(
                self._daemon.remove_transport("sim"), self._loop
            )
```

Update `_start_daemon_thread` to enable sim on startup if preference is set:

```python
def _start_daemon_thread(self):
    """Start the daemon's asyncio event loop in a background thread."""
    self._daemon = ClawdDaemon(observer=self, headless=False)

    def run_loop():
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_until_complete(self._daemon.run())

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    self._loop_ready.wait(timeout=5)

    # Enable sim transport if preference is set
    if self._sim_toggle.state and self._loop:
        self._transport_status["sim"] = False
        client = SimClient(port=SIM_DEFAULT_PORT)
        asyncio.run_coroutine_threadsafe(
            self._daemon.add_transport("sim", client), self._loop
        )
```

- [ ] **Step 7: Run all tests**

Run: `cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add host/clawd_tank_menubar/app.py host/tests/test_menubar.py
git commit -m "feat(menubar): add simulator toggle and per-transport status display"
```

### Task 6: Verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/marciorodrigues/Projects/clawd-tank/host && .venv/bin/pytest -v
```

Expected: All PASS

- [ ] **Step 2: Build simulator**

```bash
cd /Users/marciorodrigues/Projects/clawd-tank/simulator && cmake -B build && cmake --build build
```

Expected: Build succeeds

- [ ] **Step 3: Run C unit tests**

```bash
cd /Users/marciorodrigues/Projects/clawd-tank/firmware/test && make test
```

Expected: All PASS
