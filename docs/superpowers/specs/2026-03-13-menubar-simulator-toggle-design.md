# Menubar Simulator Toggle — Design Spec

## Goal

Add a checkable menu item to the macOS status bar app that enables/disables the simulator TCP transport at runtime, with per-transport connection status display and persisted preference.

## Context

The daemon supports multiple transports (BLE + simulator), but the menubar app currently only uses BLE. The simulator transport is only available via CLI flags (`--sim`, `--sim-only`). This feature exposes the simulator toggle in the GUI.

## Design

### 1. Daemon Dynamic Transport API

Two new async methods on `ClawdDaemon`:

#### `add_transport(name, client)`

```python
async def add_transport(self, name: str, client: TransportClient) -> None:
```

- Wires the client's connect/disconnect callbacks to the daemon: `client._on_connect_cb = lambda: self._on_transport_connect(name)` and `client._on_disconnect_cb = lambda: self._on_transport_disconnect(name)`. This is necessary because `SimClient` takes these callbacks at construction time, but the menubar creates the client before passing it to the daemon.
- Stores `client` in `self._transports[name]`
- Creates `asyncio.Queue()` in `self._transport_queues[name]`
- Creates and stores a sender task in `self._sender_tasks[name]`

The sender task handles initial connection via the existing `_transport_sender` logic. No need to pre-populate the queue — the sender connects, syncs time, and replays.

**Initial replay:** Currently `_transport_sender` only replays on write failure, not after initial connect. Add a `_replay_active_for()` call after the initial `_sync_time_for()` in `_transport_sender` so dynamically-added transports show existing notifications. This is harmless for BLE (no notifications at startup = replay sends nothing).

Requires storing sender tasks in a new `self._sender_tasks: dict[str, asyncio.Task]` dict. The existing `run()` method must also store its tasks in this dict (currently they are gathered anonymously).

#### `remove_transport(name)`

```python
async def remove_transport(self, name: str) -> None:
```

- Cancels the sender task and awaits clean cancellation (catch `CancelledError`)
- Disconnects the client if connected
- Removes entries from `_transports`, `_transport_queues`, and `_sender_tasks`
- Fires `_on_transport_disconnect(name)` to update observer status

The sender task may be blocked in `SimClient.connect()`'s retry loop (`asyncio.sleep`) or in `Queue.get()` — both raise `CancelledError` cleanly when the task is cancelled.

**Rapid toggle safety:** Since the menubar dispatches add/remove via `run_coroutine_threadsafe`, operations execute sequentially on the event loop. Rapid on/off/on toggling is safe — each remove fully completes (task cancelled, client disconnected) before the next add starts.

### 2. Per-Transport Status

#### Observer callback change

```python
def on_connection_change(self, connected: bool, transport: str = "") -> None:
```

The `transport` parameter is added to `DaemonObserver` Protocol. **All existing implementations must be updated:**

- `host/clawd_tank_menubar/app.py` — `ClawdTankApp.on_connection_change`
- `host/tests/test_menubar.py` — `FakeObserver.on_connection_change`
- `host/tests/test_observer.py` — `FakeObserver.on_connection_change`

The daemon's `_on_transport_connect(name)` and `_on_transport_disconnect(name)` pass the transport name as the second argument.

#### Menubar status tracking

```python
self._transport_status: dict[str, bool] = {}
```

Updated in `on_connection_change`. Used to render per-transport status lines.

When the sim transport is enabled but the simulator is not running, the sender retries connection in the background (same as BLE scanning). Status shows `"Simulator: Connecting..."` until connected or disabled.

#### Status display

Replace the single status/subtitle pair with per-transport status lines:

```
BLE: Connected
Simulator: Connecting...
```

Display names: `"ble"` → `"BLE"`, `"sim"` → `"Simulator"`.

States: `"Connected"` and `"Connecting..."` (not yet connected or lost connection — sender retries automatically in both cases).

On startup before the sim toggle is enabled, only the BLE line is shown.

#### Icon logic

Unchanged: connected if `any(self._transport_status.values())`, notification icon if count > 0, disconnected icon if no transports connected.

### 3. Menu Layout

```
BLE: Connected
Simulator: Connecting...
──────────────────────
Brightness [slider]
──────────────────────
Sleep Timeout        >
──────────────────────
Enable Simulator   ✓
──────────────────────
Launch at Login
──────────────────────
Reconnect
──────────────────────
Quit Clawd Tank
```

### 4. Toggle Behavior

**"Enable Simulator" menu item** — checkable, placed after Sleep Timeout.

- **Check (enable):** Creates `SimClient(port=19872, on_connect_cb=..., on_disconnect_cb=...)`, calls `daemon.add_transport("sim", client)` via `run_coroutine_threadsafe`. Sets menu item state to checked. Adds `"sim": False` to `_transport_status` and shows "Simulator: Connecting..." immediately.
- **Uncheck (disable):** Calls `daemon.remove_transport("sim")` via `run_coroutine_threadsafe`. Sets menu item state to unchecked. Removes `"sim"` from `_transport_status` and removes the Simulator status line.

### 5. Persistence

Preference stored in `~/.clawd-tank/preferences.json` (consistent with existing daemon PID/lock file location):

```json
{"sim_enabled": true}
```

- **Load:** On app init, read the file. If missing or malformed, default to `sim_enabled=false`.
- **Save:** On toggle, write the file. Create parent directory if needed.
- **Startup:** If `sim_enabled` is true, after the daemon's event loop is ready (`_loop_ready` fires), add the sim transport via `run_coroutine_threadsafe(daemon.add_transport(...))`.

### 6. Shutdown

The `_shutdown()` method must cancel all sender tasks in `_sender_tasks` (iterating values, cancelling, and awaiting each). This ensures dynamically-added transports (like sim) are cleaned up alongside statically-created ones (like BLE). The existing `run()` method's local task list should be replaced by `_sender_tasks`.

## Port

Fixed at `19872` (`SIM_DEFAULT_PORT`). Not configurable from the menu.

## Files Changed

- `host/clawd_tank_daemon/daemon.py` — `add_transport`, `remove_transport`, `_sender_tasks` dict, updated `run()` to use `_sender_tasks`, updated observer calls with transport name, updated `_shutdown` to cancel all sender tasks
- `host/clawd_tank_menubar/app.py` — Toggle item, per-transport status display, preference load/save, startup sim init, updated `on_connection_change` signature
- `host/tests/test_daemon.py` — Add tests for `add_transport`, `remove_transport`
- `host/tests/test_menubar.py` — Add tests for toggle state, preference persistence; update `FakeObserver.on_connection_change` signature
- `host/tests/test_observer.py` — Update `FakeObserver.on_connection_change` signature

## Not In Scope

- Configurable port from the menu
- Simulator auto-discovery
- Multiple simultaneous simulator connections
