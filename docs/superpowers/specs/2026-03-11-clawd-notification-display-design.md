# Clawd Notification Display — Design Spec

## Overview

A firmware for the Waveshare ESP32-C6-LCD-1.47 board that shows notifications when a Claude Code instance is waiting for user input. The display features Clawd — the official Claude pixel crab mascot — in a cute, animated UI that tells the user which instance needs attention.

## System Components

### 1. ESP32-C6 Firmware (ESP-IDF + LVGL)

BLE GATT server that receives notification data and renders the UI on a 320x172 LCD (landscape).

### 2. Python BLE Daemon

Background process on the host Mac that maintains a persistent BLE connection to the ESP32. Lazy-started by the first hook invocation if not already running.

### 3. Claude Code Hook

A `notification` hook that fires when Claude Code needs user input, sending the event to the daemon via Unix socket.

## Architecture

```
Claude Code Instance(s)
    │ notification hook
    ▼
clawd-notify (CLI script)
    │ Unix socket (~/.clawd/sock)
    ▼
Python Daemon (clawd_daemon)
    │ BLE GATT write
    ▼
ESP32-C6 (GATT Server "Clawd")
    │
    ▼
ST7789 LCD (320×172, landscape)
```

### Notification Lifecycle

**Adding a notification:**

1. Claude Code fires `notification` hook when waiting for input
2. Hook invokes `clawd-notify`, which reads the hook's JSON payload from stdin (containing session ID, project directory, and the notification message)
3. `clawd-notify` sends the payload to the daemon via Unix socket
4. Daemon maps the hook payload to a BLE `add` action and writes it to the ESP32
5. ESP32 animates Clawd and shows the notification

**Dismissing a notification:**

6. User resumes the Claude Code session, which fires the `notification` hook again with a "resolved" status in the hook payload
7. `clawd-notify` sends the resolved payload to the daemon
8. Daemon sends a BLE `dismiss` action for that session ID
9. ESP32 removes notification from list; Clawd returns to idle if no notifications remain

The `clawd-notify` script is stateless — it forwards hook payloads to the daemon. The daemon is responsible for translating hook payloads into BLE protocol messages and tracking active notification state.

## BLE Protocol

### Advertising

The ESP32 advertises as **"Clawd"** when no client is connected. On connection, advertising stops. On disconnect, advertising resumes and the display shows a disconnected idle state.

### GATT Service

Custom service UUID: `AECBEFD9-98A2-4773-9FED-BB2166DAA49A`

| Characteristic | UUID | Direction | Purpose |
|---|---|---|---|
| `notification_write` | `71FFB137-8B7A-47C9-9A7A-4B1B16662D9A` | Mac → ESP32 | Send/dismiss notifications |

### Message Format

JSON payloads written to `notification_write`:

```json
// Add notification
{
  "action": "add",
  "id": "a1b2c3",
  "project": "espc6-lcd-display",
  "message": "Needs approval to run tests"
}

// Dismiss notification
{
  "action": "dismiss",
  "id": "a1b2c3"
}

// Clear all
{
  "action": "clear"
}
```

- `id`: derived from the Claude Code session, used to match add/dismiss pairs
- Payloads are well under 512 bytes, fitting in a single GATT write
- JSON chosen for simplicity and debuggability

### Error Handling

- **Malformed JSON:** ESP32 silently discards the write and continues. No crash, no response.
- **Unknown action:** ESP32 ignores the message.
- **Dismiss for nonexistent ID:** ESP32 ignores it (idempotent dismiss).
- **Payload too large:** ESP32 rejects the GATT write via BLE error response (ATT error).

### Connection Behavior

- ESP32 advertises continuously when no client is connected
- Daemon connects and stays connected with automatic reconnect on disconnect
- On reconnect, daemon replays all active notifications to re-sync state

## Python Daemon & Hook Integration

### Claude Code Hook Configuration

In `~/.claude/hooks.json`:

```json
{
  "hooks": {
    "notification": [{
      "type": "command",
      "command": "clawd-notify"
    }]
  }
}
```

### `clawd-notify` CLI Script

1. Checks if daemon is running via PID file at `~/.clawd/daemon.pid`
2. If not running, starts it in the background
3. Sends the notification payload to the daemon's Unix socket at `~/.clawd/sock`

### Daemon Responsibilities

- Listens on `~/.clawd/sock` for hook messages
- Maintains a persistent BLE connection to the ESP32 (using `bleak`)
- Tracks active notifications in memory for reconnect re-sync
- On BLE reconnect, replays all active notifications to the ESP32
- Graceful shutdown: sends `clear` to ESP32, cleans up PID file

### Daemon Failure Modes

- **ESP32 not found on startup:** Daemon starts, logs a warning, and retries BLE scanning every 5 seconds. Hook messages are queued in memory and delivered when the device connects.
- **BLE disconnect during operation:** Daemon resumes scanning. Active notifications are retained in memory. On reconnect, full state is replayed.
- **Unix socket write failure (from `clawd-notify`):** `clawd-notify` exits with a non-zero status code. Claude Code hook system handles the error.
- **Stale PID file (daemon crashed):** `clawd-notify` checks if the PID in the file is alive (`kill -0`). If the process is dead, it removes the stale PID file and starts a new daemon.
- **Daemon crash recovery:** No persistent state. On restart, the daemon starts with an empty notification set. Active Claude Code sessions will re-fire their notification hooks, repopulating the state.

### Host-Side Project Structure

```
host/
  clawd-notify              # Python CLI entry point (hook calls this)
  clawd_daemon/
    __init__.py
    daemon.py               # Main daemon loop
    ble_client.py           # BLE connection management (bleak)
    socket_server.py        # Unix socket listener
  requirements.txt          # bleak, etc.
```

All host-side code is Python. `clawd-notify` is a Python script with a shebang line (`#!/usr/bin/env python3`).

## ESP32-C6 Firmware Architecture

### FreeRTOS Tasks

| Task | Priority | Responsibility |
|---|---|---|
| `ble_task` | High | NimBLE GATT server, receives writes, parses JSON |
| `ui_task` | Medium | LVGL rendering loop, animations, screen updates |
| `main_task` | Normal | Init, watchdog |

### Inter-Task Communication

- BLE task parses incoming notifications and posts them to a FreeRTOS queue
- UI task reads from the queue and updates the display
- This decouples BLE timing from rendering — no frame drops during BLE activity

### Notification State Machine

```
IDLE (Clawd idles, no notifications)
  → NEW_NOTIFICATION (animate Clawd, show notification full-screen)
    → LIST_VIEW (settle into compact list of all waiting instances)
      → NEW_NOTIFICATION (another one arrives, animate again)
      → IDLE (last notification dismissed)
```

### Notification Storage Limits

Maximum of **8 active notifications**. If a 9th arrives, the oldest notification is silently dropped to make room. This matches the expected usage pattern (1-8 main Claude Code instances) and keeps memory usage bounded on the ESP32-C6.

### Firmware Project Structure

```
firmware/
  CMakeLists.txt
  main/
    main.c                  # App entry, task creation
    ble_service.c/h         # GATT server, notification parsing
    ui_manager.c/h          # LVGL screen management, state machine
    notification.c/h        # Notification data structures, queue
    assets/                 # Clawd sprites, fonts
  components/
    lvgl/                   # LVGL v9.x, managed via ESP-IDF component manager (idf_component.yml)
```

### Display Configuration

- ST7789 driver, SPI interface
- 320x172 landscape orientation
- LVGL with double-buffered rendering
- 16-bit color (RGB565)

## UI/UX Design Boundaries

The UI/UX details will be designed by a specialized agent. This section defines the contract.

### Technical Constraints (fixed)

- Screen: 320x172 pixels, landscape, 16-bit color (RGB565)
- Clawd occupies roughly the left 1/3 (~107px wide), notification content on the right 2/3
- Clawd sprites stored as RGB565 bitmaps in flash
- LVGL handles all rendering, animations, and transitions
- Sprite frames for Clawd states: idle, alert (new notification), happy (all clear), sleeping (disconnected)

### UI/UX Agent Scope (to be designed)

- Clawd sprite sheet — exact pixel art frames and animations
- Notification entry animation (Clawd reacting, notification sliding in)
- List view layout — how multiple notifications are displayed in the right 2/3
- Transition from full-screen notification to list view
- Typography and colors — font choice, color palette for the small screen
- Idle/disconnected screen design
- Edge cases: notification text truncation, scrolling if 5+ notifications

### Firmware ↔ UI Contract

The UI layer receives structured events and owns all LVGL objects and animations:

- `ui_show_notification(id, project, message)` — add and animate a new notification
- `ui_dismiss_notification(id)` — remove a notification, transition if needed
- `ui_set_connection_state(connected)` — update Clawd's connection indicator

## Secondary Features

### WiFi (debug/setup only)

WiFi is not part of the main notification flow. WiFi is disabled by default and can be enabled at compile time via a `CONFIG_CLAWD_WIFI_ENABLED` Kconfig option. When enabled, it is available for:

- OTA firmware updates
- Debug logging / serial-over-WiFi
- Initial setup if needed (e.g., configuring BLE pairing)

### Future Considerations (not in scope)

- Physical button interaction on the ESP32 (dismiss notifications from device)
- Multiple host device support (pairing with more than one Mac)
- Notification sound/haptic feedback
