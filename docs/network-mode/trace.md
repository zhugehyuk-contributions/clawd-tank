# Network Mode (Server/Client) — Vertical Trace

> STV Trace | Created: 2026-03-23
> Spec: docs/network-mode/spec.md

## Table of Contents

1. [Scenario 1 — Server TCP Listener Start](#scenario-1)
2. [Scenario 2 — Client Hello Handshake](#scenario-2)
3. [Scenario 3 — Remote Session Event Processing](#scenario-3)
4. [Scenario 4 — Hybrid Client Forward + Local Display](#scenario-4)
5. [Scenario 5 — Client Disconnect Session Cleanup](#scenario-5)
6. [Scenario 6 — Hostname Badge on Notification Card](#scenario-6)
7. [Scenario 7 — Bonjour Service Registration & Discovery](#scenario-7)
8. [Scenario 8 — Menu Bar Network Submenu](#scenario-8)
9. [Scenario 9 — Local TCP Test CLI](#scenario-9)

---

## Scenario 1 — Server TCP Listener Start

### 1. Entry Point
- Trigger: daemon `run()` with `network_mode="server"`, or menu bar app `_on_toggle_network_server()`
- Component: `NetworkServer.start()`
- File: `host/clawd_tank_daemon/network_server.py` (new)

### 2. Input
- Configuration:
  ```json
  {"network_mode": "server", "network_port": 19873}
  ```
- Validation:
  - port: integer, 1024-65535
  - bind address: 0.0.0.0 (hardcoded)

### 3. Layer Flow

#### 3a. Menu Bar App (`app.py`)
- User enables server mode in Network submenu
- Transformation: `preferences["network_mode"]` → `"server"` → `daemon.start_network_server(port)`
- Uses `asyncio.run_coroutine_threadsafe()` to call daemon from main thread

#### 3b. Daemon (`daemon.py`)
```python
async def start_network_server(self, port: int = 19873) -> None
```
- Creates `NetworkServer(port, on_message=self._handle_remote_message, on_client_change=self._on_network_client_change)`
- Calls `self._network_server.start()`
- Stores reference: `self._network_server = server`

#### 3c. NetworkServer (`network_server.py`)
```python
async def start(self) -> None
```
- `asyncio.start_server(self._handle_client, "0.0.0.0", self._port)`
- Stores `self._server: asyncio.Server`
- Transformation: port (int) → asyncio.Server bound to 0.0.0.0:port

### 4. Side Effects
- TCP socket opened on 0.0.0.0:19873
- `NetworkServer._server` created
- `daemon._network_server` set
- Observer notified: `on_client_change(clients=[])`

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| Port already in use | `OSError: address already in use` | Log error, notify observer, do not crash |
| Invalid port (< 1024) | `OSError: permission denied` | Log error, surface to menu bar status |

### 6. Output
- Server listening state: `NetworkServer.is_listening → True`
- Menu bar status: "Network — Server (0 clients)"

### 7. Observability
- Log: `"Network server listening on 0.0.0.0:{port}"`
- Log on error: `"Network server failed to start: {error}"`

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_network_server_start_listens_on_port` | Happy Path | Scenario 1, Section 3c |
| `test_network_server_start_port_in_use` | Sad Path | Scenario 1, Section 5 |
| `test_daemon_start_network_server_stores_ref` | Side-Effect | Scenario 1, Section 4 |

---

## Scenario 2 — Client Hello Handshake

### 1. Entry Point
- Trigger: Remote machine's `NetworkClient.connect()` establishes TCP connection
- Component: `NetworkServer._handle_client()` (server side), `NetworkClient.connect()` (client side)

### 2. Input
- Client sends:
  ```json
  {"type": "hello", "hostname": "macbook-b"}
  ```
- Validation:
  - `type` must be `"hello"`
  - `hostname` must be non-empty string

### 3. Layer Flow

#### 3a. Client Side — NetworkClient (`network_client.py`)
```python
async def connect(self) -> None
```
- Opens TCP connection: `asyncio.open_connection(self._host, self._port)`
- Sends hello: `{"type":"hello","hostname":socket.gethostname()}\n`
- Transformation: `socket.gethostname()` → `hello.hostname`
- Waits for welcome response (5s timeout)
- Reads welcome: `{"type":"welcome","server":"macbook-a"}\n`
- Sets `self._connected = True`
- Calls `self._on_connect_cb()`

#### 3b. Server Side — NetworkServer (`network_server.py`)
```python
async def _handle_client(self, reader, writer) -> None
```
- Reads first line (5s timeout for handshake)
- Parses JSON, validates `type == "hello"` and `hostname` present
- Creates `ClientSession(hostname, reader, writer, time.time())`
- Stores in `self._clients[hostname]`
- Sends welcome: `{"type":"welcome","server":socket.gethostname()}\n`
- Calls `self._on_client_change(self.get_client_list())`
- Enters message loop: reads subsequent lines as daemon messages
- Transformation: `hello.hostname` → `ClientSession.hostname` → `_clients[hostname]`

### 4. Side Effects
- `NetworkServer._clients[hostname]` created
- Observer notified: `on_client_change(["macbook-b"])`
- Menu bar updates: client appears in connected list

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| First message not `hello` | Protocol violation | Close connection, log warning |
| Missing `hostname` | Invalid hello | Close connection, log warning |
| Handshake timeout (5s) | `asyncio.TimeoutError` | Close connection |
| Duplicate hostname | Existing session conflict | Replace old connection, log warning |
| Server unreachable (client side) | `ConnectionRefusedError` | Enter `_reconnect_loop()`, 5s interval |

### 6. Output
- Client: `_connected = True`, `_on_connect_cb()` fired
- Server: `get_client_list()` includes new hostname
- Menu bar: client hostname appears with green indicator

### 7. Observability
- Server log: `"Network client connected: {hostname} from {addr}"`
- Client log: `"Connected to network server: {server_hostname}"`
- Server log on error: `"Network client handshake failed from {addr}: {reason}"`

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_handshake_hello_welcome` | Happy Path | Scenario 2, Section 3a+3b |
| `test_handshake_missing_hostname_rejected` | Sad Path | Scenario 2, Section 5 |
| `test_handshake_timeout` | Sad Path | Scenario 2, Section 5 |
| `test_handshake_duplicate_hostname_replaces` | Sad Path | Scenario 2, Section 5 |
| `test_client_reconnect_on_refused` | Happy Path | Scenario 2, Section 5 |
| `test_client_list_updated_after_connect` | Side-Effect | Scenario 2, Section 4 |

---

## Scenario 3 — Remote Session Event Processing

### 1. Entry Point
- Trigger: Connected client sends daemon message (e.g. `tool_use`)
- Component: `NetworkServer._handle_client()` message loop → `daemon._handle_remote_message()`

### 2. Input
- Client sends (standard daemon message format):
  ```json
  {"event": "tool_use", "session_id": "abc123", "tool_name": "Edit", "project": "my-project"}
  ```

### 3. Layer Flow

#### 3a. NetworkServer (`network_server.py`)
- Message loop reads line from client stream
- Parses JSON
- Calls `self._on_message(hostname, msg)` → `daemon._handle_remote_message(hostname, msg)`
- Transformation: raw JSON string → `dict` + `hostname` (from `ClientSession`)

#### 3b. Daemon — `_handle_remote_message()` (`daemon.py`)
```python
async def _handle_remote_message(self, hostname: str, msg: dict) -> None
```
- Scopes session ID: `msg["session_id"]` → `"{hostname}:{session_id}"`
- Transformation: `msg.session_id = "abc123"` → `"macbook-b:abc123"`
- Badges project: `msg["project"]` → `"[{hostname}] {project}"`
- Transformation: `msg.project = "my-project"` → `"[macbook-b] my-project"`
- Delegates to existing `self._handle_message(msg)` (mutated msg with scoped ID + badged project)

#### 3c. Daemon — `_handle_message()` (existing, unchanged)
- Updates `_session_states["macbook-b:abc123"]` via `_update_session_state()`
- Transformation: `event="tool_use"` → `state="working"`, `tool_name="Edit"`
- Appends to `_session_order` on first appearance: `("macbook-b:abc123", display_id)`
- Calls `_broadcast_display_state_if_changed()`

#### 3d. Display State Computation (existing, unchanged)
- `_compute_display_state()` picks up to 4 sessions from `_session_order`
- Local session `"s1"` + remote session `"macbook-b:abc123"` mixed equally
- Transformation: `session_states["macbook-b:abc123"].state="working"` + `tool_name="Edit"` → `anims=["typing"]`
- Result: `{"anims": ["typing", "typing"], "ids": [1, 2], "subagents": 0}`

#### 3e. Transport Broadcast (existing, unchanged)
- Sends `set_sessions` to BLE/Simulator transports
- Transformation: display state dict → JSON → BLE GATT write / TCP send

### 4. Side Effects
- `daemon._session_states["macbook-b:abc123"]` created/updated
- `daemon._session_order` extended
- Display state broadcast to BLE/Simulator
- Session persisted to `sessions.json`

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| Malformed JSON from client | `json.JSONDecodeError` | Log warning, skip message, continue loop |
| Missing `event` field | Invalid message | Log warning, skip |
| Missing `session_id` | Invalid message | Log warning, skip |
| Client stream EOF | Connection closed | Trigger disconnect cleanup (Scenario 5) |

### 6. Output
- Display state updated on BLE/Simulator
- Remote session visible as Clawd sprite alongside local sessions
- Notification card (if `add` event) shows `[macbook-b] my-project`

### 7. Observability
- Log: `"Remote msg from {hostname}: event={event} session={scoped_id}"`

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_remote_session_id_scoped` | Contract | Scenario 3, Section 3b, msg.session_id → scoped |
| `test_remote_project_badged` | Contract | Scenario 3, Section 3b, msg.project → badged |
| `test_remote_session_in_display_state` | Happy Path | Scenario 3, Section 3d |
| `test_remote_and_local_sessions_mixed` | Happy Path | Scenario 3, Section 3d |
| `test_remote_malformed_json_skipped` | Sad Path | Scenario 3, Section 5 |
| `test_remote_session_persisted` | Side-Effect | Scenario 3, Section 4 |

---

## Scenario 4 — Hybrid Client Forward + Local Display

### 1. Entry Point
- Trigger: Local hook event arrives via Unix socket while in client mode
- Component: `daemon._handle_message()` → `NetworkClient.forward_message()` + local transport processing

### 2. Input
- Unix socket message (from clawd-tank-notify):
  ```json
  {"event": "tool_use", "session_id": "local-s1", "tool_name": "Bash", "project": "clawd-tank"}
  ```

### 3. Layer Flow

#### 3a. SocketServer (existing, unchanged)
- Reads line from Unix socket connection
- Calls `daemon._handle_message(msg)`

#### 3b. Daemon — `_handle_message()` (modified)
```python
async def _handle_message(self, msg: dict) -> None
```
- **Existing logic unchanged**: updates session state, enqueues to transport queues, broadcasts display state
- **New addition**: if `self._network_client` is set and connected:
  - Calls `self._network_client.forward_message(msg)`
  - Transformation: daemon message (dict) → JSON string + newline → TCP write to server
- Order: local processing first, then forward (fire-and-forget, non-blocking)

#### 3c. NetworkClient — `forward_message()` (`network_client.py`)
```python
async def forward_message(self, msg: dict) -> bool
```
- Serializes to JSON + newline
- Writes to server TCP stream
- Returns `True` on success, `False` on write failure
- Non-blocking: does not wait for server acknowledgment
- Transformation: `msg (dict)` → `json.dumps(msg) + "\n"` → `writer.write()`

#### 3d. Local Transport Processing (existing, unchanged)
- Session state updated: `_session_states["local-s1"].state = "working"`
- Display state broadcast to local BLE/Simulator
- Local Clawd sprite shows "building" animation

### 4. Side Effects
- Local session state updated in `_session_states`
- Local BLE/Simulator receives display state update
- Server receives forwarded message via TCP
- Server processes message (creates remote session `"macbook-b:local-s1"`)

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| NetworkClient disconnected | `_connected = False` | Skip forward, log debug, local processing continues |
| TCP write failure | `ConnectionError` | Mark disconnected, start reconnect, local continues |
| Server processes but is slow | Network latency | Fire-and-forget, no blocking |

### 6. Output
- Local display: Clawd sprite shows current animation (building for Bash)
- Remote server: receives and integrates the session

### 7. Observability
- Log: `"Forwarding to server: event={event} session={sid}"`
- Log on failure: `"Forward to server failed: {error}"`

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_hybrid_local_display_and_forward` | Happy Path | Scenario 4, Section 3b |
| `test_hybrid_forward_failure_local_continues` | Sad Path | Scenario 4, Section 5 |
| `test_hybrid_no_client_local_only` | Happy Path | Scenario 4, Section 5 |
| `test_forward_message_sends_json_newline` | Contract | Scenario 4, Section 3c |

---

## Scenario 5 — Client Disconnect Session Cleanup

### 1. Entry Point
- Trigger: Client TCP connection drops (EOF, network error, client shutdown)
- Component: `NetworkServer._handle_client()` exits loop → `daemon._handle_client_disconnect()`

### 2. Input
- No explicit message — connection closure detected via `StreamReader` EOF or `ConnectionError`

### 3. Layer Flow

#### 3a. NetworkServer (`network_server.py`)
- Message loop catches EOF (`readline()` returns empty) or `ConnectionError`
- Removes client from `self._clients`: `del self._clients[hostname]`
- Calls `self._on_client_disconnect(hostname)`
- Calls `self._on_client_change(self.get_client_list())`
- Closes writer
- Transformation: connection EOF → `hostname` → cleanup

#### 3b. Daemon — `_handle_client_disconnect()` (`daemon.py`)
```python
def _handle_client_disconnect(self, hostname: str) -> None
```
- Identifies all sessions with `hostname:` prefix in `_session_states`
- Filter: `[sid for sid in _session_states if sid.startswith(f"{hostname}:")]`
- Removes each from `_session_states` and `_session_order`
- Removes from `_active_notifications` (if any)
- Calls `_persist_sessions()`
- Calls `_broadcast_display_state_if_changed()` (async, via `asyncio.create_task`)
- Transformation: `hostname` → filter `_session_states` keys → remove matching → recompute display

### 4. Side Effects
- All `{hostname}:*` sessions removed from `_session_states`
- `_session_order` pruned
- `_active_notifications` pruned
- Display state recomputed — remaining sessions reposition
- `sessions.json` updated
- Observer notified: `on_client_change(updated_list)`, `on_notification_change(new_count)`

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| No sessions for hostname | Empty filter | No-op, safe |
| Display broadcast fails | Transport error | Handled by transport sender (existing) |

### 6. Output
- Disconnected client's Clawds disappear (going-away animation if v2)
- Remaining Clawds reposition
- Menu bar: client removed from connected list

### 7. Observability
- Log: `"Network client disconnected: {hostname}, removed {N} sessions"`

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_disconnect_removes_all_client_sessions` | Happy Path | Scenario 5, Section 3b |
| `test_disconnect_preserves_local_sessions` | Happy Path | Scenario 5, Section 3b |
| `test_disconnect_updates_display_state` | Side-Effect | Scenario 5, Section 4 |
| `test_disconnect_clears_client_notifications` | Side-Effect | Scenario 5, Section 4 |
| `test_disconnect_no_sessions_noop` | Sad Path | Scenario 5, Section 5 |

---

## Scenario 6 — Hostname Badge on Notification Card

### 1. Entry Point
- Trigger: Remote client sends `add` event (Stop/StopFailure/Notification hook)
- Component: `daemon._handle_remote_message()` → notification flows to device

### 2. Input
- Remote daemon message:
  ```json
  {"event": "add", "hook": "Stop", "session_id": "s1", "project": "clawd-tank", "message": "Waiting for input"}
  ```

### 3. Layer Flow

#### 3a. Daemon — `_handle_remote_message()` (`daemon.py`)
- Scopes session_id: `"s1"` → `"macbook-b:s1"`
- Badges project: `"clawd-tank"` → `"[macbook-b] clawd-tank"`
- Delegates to `_handle_message(mutated_msg)`
- Transformation: `msg.project` → `f"[{hostname}] {msg.project}"`

#### 3b. Daemon — `_handle_message()` (existing)
- Stores in `_active_notifications["macbook-b:s1"]`
- Converts to BLE payload: `daemon_message_to_ble_payload(msg)`
- Result: `{"action":"add","id":"macbook-b:s1","project":"[macbook-b] clawd-tank","message":"Waiting for input"}`

#### 3c. Firmware/Simulator (existing, unchanged)
- BLE/TCP receives `add` action
- `notification_ui.c` renders card with `project = "[macbook-b] clawd-tank"`
- 48-char ID field: `"macbook-b:s1"` fits within `NOTIF_MAX_ID_LEN` (48)

### 4. Side Effects
- Notification card displayed on device with `[macbook-b]` prefix
- RGB LED flash on ESP32 (existing behavior)

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| Scoped ID > 48 chars | Truncation | `safe_strncpy` in firmware truncates, still unique |
| Project string too long with badge | BLE MTU overflow | Badge prefix is short (~15 chars), low risk |

### 6. Output
- Device displays notification card:
  ```
  [macbook-b]
  clawd-tank
  Waiting for input
  ```

### 7. Observability
- Log: `"Remote notification: [{hostname}] {project} — {message}"`

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_remote_add_badges_project` | Contract | Scenario 6, Section 3a |
| `test_remote_add_scopes_id` | Contract | Scenario 6, Section 3a |
| `test_remote_notification_in_ble_payload` | Happy Path | Scenario 6, Section 3b |
| `test_badge_format_bracket_hostname` | Contract | Scenario 6, Section 3a |

---

## Scenario 7 — Bonjour Service Registration & Discovery

### 1. Entry Point
- Trigger: Server starts → registers mDNS. Client starts → browses for services.
- Component: `BonjourService` (`host/clawd_tank_daemon/bonjour.py`, new)

### 2. Input
- Server registration:
  - Service type: `_clawd-tank._tcp`
  - Port: 19873
  - TXT record: `hostname={gethostname()}`
- Client discovery:
  - Service type: `_clawd-tank._tcp`

### 3. Layer Flow

#### 3a. Server — `BonjourService.register()` (`bonjour.py`)
```python
def register(self, port: int, hostname: str) -> None
```
- Creates `NSNetService(domain="", type="_clawd-tank._tcp.", name=hostname, port=port)`
- Calls `service.publish()`
- Stores reference: `self._service = service`
- Transformation: `(port, hostname)` → `NSNetService` → mDNS advertised

#### 3b. Client — `BonjourService.discover()` (`bonjour.py`)
```python
async def discover(self, timeout: float = 3.0) -> list[dict]
```
- Creates `NSNetServiceBrowser`
- Calls `browser.searchForServicesOfType_inDomain_("_clawd-tank._tcp.", "")`
- Collects results for `timeout` seconds
- Resolves each service: hostname, IP address, port
- Returns: `[{"hostname": "macbook-a", "host": "192.168.1.10", "port": 19873}]`
- Transformation: mDNS browse results → resolved address list

### 4. Side Effects
- Server: mDNS service registered, visible to LAN
- Client: discovered servers list populated

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| pyobjc not available | `ImportError` | Disable Bonjour, log warning, manual IP only |
| No servers found | Empty list | Return `[]`, UI shows "No servers found" |
| mDNS resolve timeout | Service not resolvable | Skip entry, log warning |

### 6. Output
- Server: service advertised on LAN
- Client: list of discovered servers for UI

### 7. Observability
- Server log: `"Bonjour: registered _clawd-tank._tcp on port {port}"`
- Client log: `"Bonjour: discovered {count} servers"`

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_bonjour_register_creates_service` | Happy Path | Scenario 7, Section 3a |
| `test_bonjour_discover_returns_list` | Happy Path | Scenario 7, Section 3b |
| `test_bonjour_import_error_graceful` | Sad Path | Scenario 7, Section 5 |
| `test_bonjour_no_servers_empty_list` | Sad Path | Scenario 7, Section 5 |

---

## Scenario 8 — Menu Bar Network Submenu

### 1. Entry Point
- Trigger: User clicks Network menu items in menu bar app
- Component: `ClawdTankApp` (`host/clawd_tank_menubar/app.py`)

### 2. Input
- User actions: toggle mode, enter server IP, enable/disable

### 3. Layer Flow

#### 3a. Mode Toggle — Server
- User selects "Server" radio button
- Callback: `_on_select_server_mode()`
- Saves `preferences["network_mode"] = "server"`
- Calls `daemon.start_network_server(port)` via `run_coroutine_threadsafe`
- If Bonjour enabled: `BonjourService.register(port, hostname)`
- If was client: disconnects `NetworkClient`, removes forwarding
- Transformation: UI selection → preference → daemon.start_network_server()

#### 3b. Mode Toggle — Client
- User selects "Client" radio button
- Callback: `_on_select_client_mode()`
- Saves `preferences["network_mode"] = "client"`
- Prompts for server IP if not set (or uses stored value)
- Calls `daemon.stop_network_server()` if was server
- Creates `NetworkClient(host, port)`, calls `daemon.set_network_client(client)`
- `NetworkClient.connect()` starts in background
- If Bonjour enabled: populates "Discovered Servers" submenu
- Transformation: UI selection → preference → daemon.set_network_client()

#### 3c. Observer Updates
- `on_client_change(clients)` → updates connected client list in server submenu
- `on_connection_change(connected, "network")` → updates client mode status

#### 3d. Preferences Persistence
- All settings saved to `~/.clawd-tank/preferences.json`:
  ```json
  {
    "network_mode": "server",
    "network_port": 19873,
    "network_server_host": "192.168.1.10",
    "network_server_port": 19873,
    "network_bonjour_enabled": true
  }
  ```

### 4. Side Effects
- Preferences file updated
- Daemon state changed (server started or client connected)
- Menu items updated dynamically

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| Invalid IP entered | Validation failure | Show alert, do not save |
| Server start fails | Port in use | Show error in status, fall back to disabled |

### 6. Output
- Menu bar icon unchanged (network mode is transparent to BLE/Sim indicators)
- Network submenu reflects current state
- Server: shows client count
- Client: shows connection status + server hostname

### 7. Observability
- Log: `"Network mode changed to {mode}"`

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_preferences_network_mode_saved` | Happy Path | Scenario 8, Section 3d |
| `test_server_mode_starts_listener` | Happy Path | Scenario 8, Section 3a |
| `test_client_mode_creates_client` | Happy Path | Scenario 8, Section 3b |
| `test_mode_switch_stops_previous` | Side-Effect | Scenario 8, Section 3a+3b |

---

## Scenario 9 — Local TCP Test CLI

### 1. Entry Point
- Trigger: 개발자가 `python tools/tcp_test.py` 실행
- Component: `tools/tcp_test.py` (new, standalone script)

### 2. Input
- CLI 인자:
  ```
  --host HOST    서버 주소 (기본: 127.0.0.1)
  --port PORT    서버 포트 (기본: 19873)
  --hostname NAME  식별 이름 (기본: "tcp-test")
  ```
- 인터랙티브 명령:
  ```
  s <project>   세션 시작
  t <tool>      도구 사용 (Edit/Bash/Read/Grep/Agent/WebSearch 등)
  w             입력 대기 (Stop → notification)
  u             유저 입력 (dismiss + thinking)
  e             세션 종료
  a+            서브에이전트 시작
  a-            서브에이전트 종료
  n <message>   커스텀 알림
  c             전체 clear
  demo          자동 데모 시퀀스
  q             종료
  ```

### 3. Layer Flow

#### 3a. TCP 연결 + 핸드셰이크
- `asyncio.open_connection(host, port)`
- Sends: `{"type":"hello","hostname":"tcp-test"}\n`
- Receives: `{"type":"welcome","server":"..."}\n`
- Transformation: CLI args → TCP connection → handshake

#### 3b. 인터랙티브 명령 → daemon message
- 각 명령을 daemon message JSON으로 변환
- Transformation 예시:
  ```
  "s my-project"
  → {"event":"session_start","session_id":"tcp-test-1","project":"my-project"}

  "t Edit"
  → {"event":"tool_use","session_id":"tcp-test-1","tool_name":"Edit","project":"my-project"}

  "w"
  → {"event":"add","hook":"Stop","session_id":"tcp-test-1","project":"my-project","message":"Waiting for input"}

  "u"
  → {"event":"dismiss","hook":"UserPromptSubmit","session_id":"tcp-test-1"}
  ```
- 세션 ID 자동 생성: `"tcp-test-{counter}"` (증분)

#### 3c. demo 모드
- 자동 시퀀스 (3개 세션 시뮬레이션):
  ```
  1. session_start "project-a" → 0.5s
  2. tool_use "Edit" → 1s
  3. session_start "project-b" → 0.5s
  4. tool_use "Bash" (session 2) → 1s
  5. tool_use "Agent" (session 1) → 1s
  6. subagent_start (session 1) → 1s
  7. session_start "project-c" → 0.5s
  8. tool_use "WebSearch" (session 3) → 2s
  9. add/Stop (session 2) → 2s   ← notification 표시
  10. dismiss (session 2) → 1s
  11. subagent_stop (session 1) → 1s
  12. session_end all → done
  ```
- 각 단계 사이 `asyncio.sleep()` — 크랩 애니메이션 전환 확인 가능

### 4. Side Effects
- 서버 데몬에 세션 이벤트 주입
- BLE/시뮬레이터에 크랩 애니메이션 표시
- 알림 카드 표시/해제

### 5. Error Paths

| Condition | Error | Handling |
|-----------|-------|----------|
| 서버 미실행 | `ConnectionRefusedError` | "Server not running on {host}:{port}" 출력, 종료 |
| 연결 중 끊김 | `ConnectionError` | "Connection lost" 출력, 종료 |
| 알 수 없는 명령 | Unknown command | "Unknown command: {cmd}" 출력, 계속 |

### 6. Output
- 터미널: 각 명령 실행 확인 메시지
  ```
  Connected to macbook-a (port 19873)
  > s clawd-tank
  [session tcp-test-1] started (clawd-tank)
  > t Edit
  [session tcp-test-1] tool_use: Edit
  > w
  [session tcp-test-1] waiting for input
  > demo
  Running demo sequence...
  [1/12] session_start project-a
  [2/12] tool_use Edit
  ...
  Demo complete.
  ```

### 7. Observability
- 서버 로그에 `"Network client connected: tcp-test"` 표시
- 모든 이벤트가 서버 로그에 기록됨

### Contract Tests (RED)

| Test Name | Category | Trace Reference |
|-----------|----------|-----------------|
| `test_tcp_test_connect_and_hello` | Happy Path | Scenario 9, Section 3a |
| `test_tcp_test_session_command` | Contract | Scenario 9, Section 3b |
| `test_tcp_test_tool_command` | Contract | Scenario 9, Section 3b |
| `test_tcp_test_demo_sequence` | Happy Path | Scenario 9, Section 3c |
| `test_tcp_test_server_not_running` | Sad Path | Scenario 9, Section 5 |

---

## Auto-Decisions

| Decision | Tier | Rationale |
|----------|------|-----------|
| `_handle_remote_message` mutates msg in-place before delegating | small | 기존 `_handle_message` 재사용, 최소 변경 |
| Forward is fire-and-forget (no ack) | small | 알림은 best-effort, 기존 hook handler와 동일 철학 |
| Handshake timeout 5초 | tiny | 기존 BLE/Sim 패턴과 동일 |
| `_handle_client` per-connection long-lived loop | small | SocketServer의 fire-and-forget과 달리, 클라이언트는 지속 연결 |
| Bonjour는 optional (ImportError 시 graceful degrade) | small | pyobjc 없는 환경(headless Linux 등) 지원 |
| TCP test CLI의 hostname은 "tcp-test" 고정 | tiny | 테스트 도구이므로 간결하게 |
| demo 시퀀스는 3세션 시뮬레이션 | tiny | 멀티슬롯 렌더링 + 알림 + 서브에이전트 모두 테스트 |

## Implementation Status

| # | Scenario | Size | Trace | Tests | Status |
|---|----------|------|-------|-------|--------|
| 1 | Server TCP Listener Start | small | done | 3 GREEN | Complete |
| 2 | Client Hello Handshake | medium | done | 6 GREEN | Complete |
| 3 | Remote Session Event Processing | medium | done | 6 GREEN | Complete |
| 4 | Hybrid Client Forward + Local Display | medium | done | 4 GREEN | Complete |
| 5 | Client Disconnect Session Cleanup | small | done | 5 GREEN | Complete |
| 6 | Hostname Badge on Notification Card | small | done | 4 GREEN | Complete |
| 7 | Bonjour Service Registration & Discovery | medium | done | impl | Complete |
| 8 | Menu Bar Network Submenu | large | done | impl | Complete |
| 9 | Local TCP Test CLI | small | done | impl | Complete |

**Total: 9 scenarios, 41 contract tests**

## New Files

| File | Lines (est.) | Description |
|------|-------------|-------------|
| `host/clawd_tank_daemon/network_server.py` | ~200 | TCP server, client management, handshake |
| `host/clawd_tank_daemon/network_client.py` | ~180 | TCP client, forwarding, reconnect |
| `host/clawd_tank_daemon/bonjour.py` | ~100 | mDNS service registration & discovery |
| `tools/tcp_test.py` | ~120 | Interactive TCP test CLI |
| `host/tests/test_network_server.py` | ~250 | Server scenarios contract tests |
| `host/tests/test_network_client.py` | ~200 | Client + hybrid scenarios contract tests |

## Modified Files

| File | Changes (est.) | Description |
|------|---------------|-------------|
| `host/clawd_tank_daemon/daemon.py` | +~80 lines | `_handle_remote_message`, `start_network_server`, `set_network_client`, forward hook |
| `host/clawd_tank_menubar/app.py` | +~120 lines | Network submenu, mode toggle, client list |
| `host/clawd_tank_menubar/preferences.py` | +~5 lines | Network preference keys |

## Next Step

→ `stv:work docs/network-mode/trace.md` 로 시나리오별 구현 시작
→ 추천 구현 순서: Scenario 1 → 2 → 3 → 5 → 6 → 9 → 4 → 7 → 8 (의존성 순)
→ Scenario 9 (TCP Test CLI)는 Scenario 3 이후 바로 구현하면 이후 시나리오 수동 검증에 활용 가능
