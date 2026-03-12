# Clawd Notification Display — TODO

## Status

Firmware builds, flashes, and runs on the Waveshare ESP32-C6-LCD-1.47 board.
BLE advertising works, notifications can be sent and dismissed via BLE GATT writes.
All 35 tests pass (11 C + 24 Python). Clawd sprite animations and notification card UI are implemented.

---

## UI/UX Design (Major)

- [x] **Clawd sprite sheet** — 8-bit pixel art crab in RGB565 bitmaps stored in flash
  - Idle animation (breathing/blinking)
  - Alert state (new notification — bouncing, waving claws)
  - Happy state (all notifications cleared)
  - Sleeping/disconnected state
- [ ] **Notification entry animation** — Clawd reacting + notification sliding in from the right
  - Scene-width slide animation done (400ms ease-out). Notification panel fade still stubbed (`/* TODO: fade animation */` in `notification_ui.c`).
- [x] **List view layout** — compact layout for multiple notifications in the right 2/3 of the screen
- [ ] **Transition animation** — full-screen new notification → compact list view
  - Scene width transition done via `lv_anim`. Blocked on notification panel fade (same as entry animation above).
- [x] **Typography and colors** — font choice and color palette for the 320x172 screen
- [x] **Idle/disconnected screen** — what shows when no notifications are active
- [ ] **Text truncation and scrolling** — handle long project names and messages, scrolling for 5+ notifications
  - Truncation and clipping done (`snprintf` + `LV_LABEL_LONG_CLIP`). Marquee/scroll for overflow text not implemented.
- [x] **Notification ordering** — render entries by insertion `seq` order instead of slot index

## Hook Integration (Setup)

- [ ] **Install Claude Code hooks** — run `host/install-hooks.sh` and merge the output into `~/.claude/settings.json` to wire up `Notification`, `UserPromptSubmit`, and `SessionEnd` hooks
  - Script exists but only prints JSON snippet — does not auto-install into settings.
- [ ] **Test full hook→daemon→BLE→display pipeline** — verify notifications appear when Claude Code goes idle and dismiss when user responds

## Firmware Hardening (Medium Priority)

Unchecked return values that can cause silent failures on hardware:

- [ ] **`ble_gatts_count_cfg` / `ble_gatts_add_svcs`** (`ble_service.c:199-200`) — wrap with `ESP_ERROR_CHECK`. GATT registration failure means the device advertises but ignores all writes
- [ ] **`ble_hs_mbuf_to_flat`** (`ble_service.c:105`) — check return value before using `copied` to null-terminate buffer
- [ ] **`lv_display_create`** (`display.c:116`) — NULL check with abort. Memory exhaustion causes NULL pointer UB in all subsequent `lv_display_set_*` calls
- [ ] **`xTaskCreate`** (`main.c:48`) — check return against `pdPASS`. Silent UI task failure leaves device advertising but non-functional
- [ ] **`ble_svc_gap_device_name_set`** (`ble_service.c:195`) — check return value
- [ ] **`ble_hs_util_ensure_addr(0)`** (`ble_service.c:179`) — add before `start_advertising()` in `ble_on_sync`. NimBLE best practice for ESP32-C6
- [ ] **DMA buffer `assert` → `configASSERT`** (`display.c:122`) — bare `assert` is compiled out with `NDEBUG`

## Python Host Hardening (Medium Priority)

- [ ] **`_ble_sender` ValueError crash** (`daemon.py:76`) — `daemon_message_to_ble_payload` raises `ValueError` on unknown event, killing the sender loop permanently. Add `try/except ValueError` with `logger.error` and `continue`
- [x] **Failed BLE dismiss drops silently** (`daemon.py:79`) — now triggers reconnect + `_replay_active` on write failure instead of silently dropping
- [ ] **Socket length framing** (`socket_server.py:39`) — `reader.read(4096)` has no message boundary guarantee. Document the 4096-byte limit or switch to newline-framed messages
- [ ] **`sys.exit(1)` in hook** (`clawd-notify:77`) — non-zero exit may surface errors in Claude Code. Consider `sys.exit(0)` since notifications are best-effort
- [ ] **Log file context manager** (`clawd-notify:43`) — `open()` not in `with` block; `Popen` failure leaks the handle
- [ ] **Broad `except Exception`** (`socket_server.py:43`) — use `logger.exception()` for tracebacks and distinguish `JSONDecodeError` from `TimeoutError`

## Testing Improvements (Low Priority)

- [ ] **Add sanitizers to C test Makefile** — `-fsanitize=address,undefined -Werror` catches off-by-one writes in `write_slot`/`memset` at zero cost
- [ ] **Test `_replay_active`** — verify it sends active notifications, handles concurrent mutation
- [ ] **Test BLE write failure → reconnect → replay path**
- [ ] **Test unknown event in `_handle_message`** — currently falls through to queue, eventually crashes `_ble_sender`
  - Protocol-layer test exists (`test_unknown_hook_event_returns_none`). Daemon-level `_handle_message` test still missing.
- [ ] **Test `cwd=""`** (empty string explicitly) — verify `Path("").name` triggers the `"unknown"` fallback

## Code Quality (Low Priority)

- [ ] **Document `_lock_t` locking intent** (`ui_manager.c`) — comment explaining the lock covers both `rebuild_ui()` and `lv_timer_handler()`
- [ ] **Comment `display_init()` return** (`main.c:42`) — return value intentionally discarded; LVGL tracks default display internally
- [ ] **`install-hooks.sh` add `set -u`** — prevent silent empty-variable expansion
- [ ] **LVGL mutex migration** — consider switching from `_lock_t` to LVGL's built-in `lv_lock()`/`lv_unlock()` for proper flush-ready integration (production hardening)

## Future Considerations (Out of Scope)

- Physical button interaction (dismiss notifications from the device)
- Multiple host device support (pairing with more than one Mac)
- Notification sound/haptic feedback
- OTA firmware updates over WiFi
