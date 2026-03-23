# Network Mode (Server/Client) — Spec

> STV Spec | Created: 2026-03-23

## 1. Overview

Clawd Tank 데몬에 네트워크 모드를 추가하여, 여러 머신의 Claude Code 세션을 하나의 물리 디스플레이(또는 시뮬레이터)에 통합 표시한다.

현재 데몬은 로컬 Unix socket으로만 hook 이벤트를 수신하지만, TCP API 포트를 열어 원격 머신의 세션 상태를 직접 수신할 수 있도록 확장한다. 각 머신에서 데몬이 서버 또는 클라이언트 모드로 동작하며, 클라이언트는 하이브리드 모드로 로컬 디스플레이를 유지하면서 서버에도 세션을 포워딩한다.

## 2. User Stories

- **US-1**: 개발자로서, 맥북 A에 연결된 Clawd Tank 디스플레이에서 맥북 A + B + C의 Claude Code 세션을 동시에 모니터링하고 싶다.
- **US-2**: 개발자로서, 맥북 B에서 Claude Code를 사용하면서 로컬 시뮬레이터에도 자기 세션을 보고, 동시에 맥북 A 서버에 세션 상태를 포워딩하고 싶다.
- **US-3**: 개발자로서, 외부 시스템(CI/CD, 다른 AI 에이전트 등)에서 TCP API로 직접 세션 상태를 서버 데몬에 전송하고 싶다.
- **US-4**: 개발자로서, 메뉴바 앱에서 서버/클라이언트 모드를 전환하고, 서버 IP를 설정하고, 연결된 클라이언트 목록을 확인하고 싶다.
- **US-5**: 개발자로서, 같은 LAN의 서버를 Bonjour로 자동 발견하여 수동 IP 입력 없이 연결하고 싶다.

## 3. Acceptance Criteria

- [ ] 서버 모드: TCP 포트(기본 19873)에서 원격 클라이언트 연결을 수신하고, 원격 세션을 로컬 세션과 통합하여 BLE/시뮬레이터에 표시
- [ ] 클라이언트 모드 (하이브리드): 로컬 hook 이벤트를 서버로 포워딩하면서 로컬 BLE/시뮬레이터에도 자기 세션 표시
- [ ] TCP 프로토콜: 기존 daemon message JSON 형식 재사용, 뉴라인 구분
- [ ] 핸드셰이크: 클라이언트 연결 시 hostname 식별 (`hello`/`welcome`)
- [ ] 세션 ID 충돌 방지: 원격 세션은 `{hostname}:{session_id}` 형태로 스코핑
- [ ] 알림 카드에 원격 세션의 호스트네임 뱃지 표시 (`[macbook-b]`)
- [ ] 메뉴바 앱: Network 서브메뉴에서 모드 전환, IP/포트 설정, 연결 상태 표시
- [ ] 서버: 연결된 클라이언트 목록 메뉴 항목으로 표시
- [ ] Bonjour/mDNS: 서버가 `_clawd-tank._tcp` 서비스 등록, 클라이언트가 자동 발견
- [ ] 자동 재연결: 클라이언트가 서버 연결 끊어지면 5초 간격 재시도
- [ ] 기존 기능 유지: 서버 모드에서 로컬 hooks + BLE + 시뮬레이터 모두 정상 동작

## 4. Scope

### In-Scope
- TCP 네트워크 서버 (서버 모드)
- TCP 네트워크 클라이언트 (클라이언트 모드, 하이브리드)
- 세션 ID 스코핑 (hostname prefix)
- 호스트네임 뱃지 (알림 카드)
- 메뉴바 앱 Network 서브메뉴
- Bonjour/mDNS 서비스 등록 및 발견
- 자동 재연결 로직
- preferences.json 확장
- TCP 테스트 CLI (`tools/tcp_test.py`) — BLE/hooks 없이 로컬 TCP로 세션 이벤트 주입

### Out-of-Scope
- 인증/암호화 (Open LAN trust 모델)
- 원격 세션의 크랩 색상 차별화 (v2 이후)
- 웹 UI 대시보드
- 방화벽 자동 설정
- NAT traversal / WAN 지원

## 5. Architecture

### 5.1 System Topology

```
┌─ MacBook A (Server Mode) ─────────────────────────────────┐
│                                                             │
│  Claude Code hooks → notify → Unix socket ─┐               │
│                                             ▼               │
│  TCP:19873 ◄─── remote clients ──► NetworkServer            │
│                                        │                    │
│                                        ▼                    │
│                               ClawdDaemon                   │
│                            (session aggregation)            │
│                              │          │                   │
│                              ▼          ▼                   │
│                            BLE     Simulator                │
│                          (ESP32)    (SDL2)                   │
└─────────────────────────────────────────────────────────────┘

┌─ MacBook B (Client Mode, Hybrid) ──────────────────────────┐
│                                                             │
│  Claude Code hooks → notify → Unix socket                   │
│                                        │                    │
│                                        ▼                    │
│                               ClawdDaemon                   │
│                            ┌──────┼──────────┐              │
│                            ▼      ▼          ▼              │
│                     NetworkClient  BLE    Simulator          │
│                      (→ Server)  (local)  (local)           │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─ External System ───────────────────────────────────────────┐
│  Custom script → TCP:19873 → Server daemon                  │
│  (daemon message JSON format)                               │
└─────────────────────────────────────────────────────────────┘

┌─ Local Testing (tcp_test.py) ───────────────────────────────┐
│  localhost → TCP:19873 → Server daemon (same machine)       │
│  Interactive CLI로 세션 이벤트 주입, BLE/hooks 없이 테스트    │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Component Structure

#### 5.2.1 NetworkServer (`network_server.py`, ~200줄)

서버 모드에서 TCP 포트를 열고 원격 클라이언트 연결을 관리.

```
NetworkServer
├── _host: str                          # 바인드 주소 (0.0.0.0)
├── _port: int                          # 기본 19873
├── _server: asyncio.Server             # TCP 서버
├── _clients: dict[str, ClientSession]  # hostname → 클라이언트 세션
├── _on_message: Callable               # daemon._handle_remote_message()
├── _on_client_change: Callable         # observer 콜백
│
├── start() → None
├── stop() → None
├── get_client_list() → list[str]       # 연결된 hostname 목록
└── _handle_client(reader, writer) → None  # per-connection handler
```

**ClientSession:**
```
ClientSession
├── hostname: str
├── reader: asyncio.StreamReader
├── writer: asyncio.StreamWriter
├── connected_at: float
└── last_message: float
```

**연결 프로토콜:**
```
Client → Server:  {"type":"hello","hostname":"macbook-b"}\n
Server → Client:  {"type":"welcome","server":"macbook-a"}\n
Client → Server:  {"event":"session_start","session_id":"abc",...}\n
Client → Server:  {"event":"tool_use","session_id":"abc",...}\n
...
```

핸드셰이크 후 클라이언트는 기존 daemon message 형식(hook_payload_to_daemon_message 출력)을 뉴라인 구분으로 스트리밍. 서버는 각 메시지를 `_on_message(hostname, msg)` 콜백으로 전달.

#### 5.2.2 NetworkClient (`network_client.py`, ~180줄)

클라이언트 모드에서 서버에 연결하여 로컬 세션 이벤트를 포워딩.

```
NetworkClient
├── _host: str                    # 서버 IP/hostname
├── _port: int                    # 서버 포트
├── _hostname: str                # 자기 hostname
├── _reader: asyncio.StreamReader
├── _writer: asyncio.StreamWriter
├── _connected: bool
├── _on_connect_cb: Callable
├── _on_disconnect_cb: Callable
│
├── connect() → None              # 핸드셰이크 포함
├── disconnect() → None
├── forward_message(msg: dict) → bool  # 서버로 전달
└── _reconnect_loop() → None      # 5초 간격 재시도
```

NetworkClient는 TransportClient Protocol을 구현하지 않는다 — 출력 트랜스포트(BLE/Sim)와 달리 입력 포워더이므로 별도 인터페이스.

#### 5.2.3 BonjourService (`bonjour.py`, ~100줄)

macOS Bonjour/mDNS 서비스 등록 및 발견.

```
BonjourService
├── register(port: int, hostname: str) → None   # 서버: 서비스 등록
├── unregister() → None
├── discover() → list[dict]                      # 클라이언트: 서비스 검색
│   # Returns: [{"hostname": "macbook-a", "host": "192.168.1.10", "port": 19873}]
└── _browse_callback(...)                        # pyobjc NSNetService 콜백
```

pyobjc의 `Foundation.NSNetServiceBrowser` 사용 (메뉴바 앱이 이미 pyobjc 의존).

#### 5.2.4 TCP 테스트 CLI (`tools/tcp_test.py`, ~120줄)

BLE 디바이스나 Claude Code hooks 없이, 로컬 TCP 포트로 직접 세션 이벤트를 주입하여 디스플레이를 테스트. 기존 `tools/ble_interactive.py` 패턴 재사용.

```
사용법:
  python tools/tcp_test.py                    # localhost:19873 기본
  python tools/tcp_test.py --host 192.168.1.10 --port 19873

인터랙티브 명령:
  s <name>     — 새 세션 시작 (session_start)
  t <tool>     — 도구 사용 (tool_use: Edit/Bash/Read/Agent/WebSearch)
  w            — 입력 대기 (Stop → add notification)
  u            — 유저 입력 (UserPromptSubmit → dismiss + thinking)
  e            — 세션 종료 (SessionEnd)
  a+           — 서브에이전트 시작
  a-           — 서브에이전트 종료
  n <msg>      — 커스텀 알림 추가
  c            — 전체 clear
  demo         — 자동 데모 (3세션 시뮬레이션, 타이밍 포함)
  q            — 종료
```

핸드셰이크 자동 처리 (hostname = `"tcp-test"`), 세션 ID 자동 생성.

#### 5.2.5 ClawdDaemon 확장 (`daemon.py`, +~80줄)

```python
# 새 메서드
async def _handle_remote_message(self, hostname: str, msg: dict) -> None
    """원격 클라이언트의 메시지를 호스트네임 스코핑하여 처리."""

def _scope_session_id(self, hostname: str, session_id: str) -> str
    """'{hostname}:{session_id}' 형태로 변환."""

async def start_network_server(self, port: int = 19873) -> None
async def stop_network_server(self) -> None

def set_network_client(self, client: NetworkClient) -> None
    """포워딩 클라이언트 등록."""

# _handle_message 수정: 클라이언트 모드면 NetworkClient.forward_message() 호출
```

#### 5.2.5 메뉴바 앱 확장 (`app.py`, +~120줄)

```
Network 서브메뉴:
├── Mode: Server ◉ / Client ○        # 라디오 선택
├── ─────────────────
├── [서버 모드]
│   ├── Port: 19873
│   ├── Status: Listening (3 clients)
│   ├── ─────
│   ├── macbook-b ✅
│   └── macbook-c ✅
├── [클라이언트 모드]
│   ├── Server: 192.168.1.10
│   ├── Port: 19873
│   ├── Status: Connected ✅
│   ├── ─────
│   └── Discovered Servers ▸
│       ├── macbook-a.local (192.168.1.10)
│       └── macbook-d.local (192.168.1.20)
```

### 5.3 TCP 프로토콜

**포트**: 19873 (시뮬레이터 19872의 다음)

**프로토콜**: 뉴라인 구분 JSON (기존 Unix socket / 시뮬레이터 TCP와 동일 패턴)

**연결 흐름:**
```
1. TCP 연결 수립
2. Client → Server: hello 메시지 (hostname 식별)
3. Server → Client: welcome 응답 (서버 hostname)
4. Client → Server: daemon message 스트리밍 (기존 형식)
5. 연결 종료 시 서버가 해당 클라이언트의 모든 세션 정리
```

**메시지 형식 (기존 daemon message 재사용):**
```json
{"event":"session_start", "session_id":"abc123", "project":"my-project"}
{"event":"tool_use", "session_id":"abc123", "tool_name":"Edit"}
{"event":"add", "hook":"Stop", "session_id":"abc123", "project":"my-project", "message":"Waiting for input"}
{"event":"dismiss", "hook":"UserPromptSubmit", "session_id":"abc123"}
{"event":"subagent_start", "session_id":"abc123", "agent_id":"agent-1"}
```

**서버 측 세션 ID 변환:**
```
수신: {"event":"tool_use", "session_id":"abc123", ...}
내부: session_id = "macbook-b:abc123"  (hostname prefix 추가)
```

**클라이언트 연결 해제 시:**
- 서버가 해당 hostname의 모든 세션을 즉시 제거
- 디스플레이 상태 재계산 및 브로드캐스트

### 5.4 세션 ID 스코핑

원격 세션과 로컬 세션의 ID 충돌을 방지하기 위해:

- 로컬 세션: `session_id` 그대로 사용 (기존 호환)
- 원격 세션: `{hostname}:{session_id}` 형태로 변환
- `_session_states` dict에 혼합 저장
- `_compute_display_state()`는 변경 없이 동작 (세션 ID 형식에 무관)

### 5.5 호스트네임 뱃지

알림 카드의 project 필드를 확장하여 원격 세션에 호스트네임 표시:

```
기존: project = "clawd-tank"
원격: project = "[macbook-b] clawd-tank"
```

daemon이 원격 메시지를 `_handle_remote_message()`에서 처리할 때 project 필드에 hostname prefix를 추가. 펌웨어/시뮬레이터 측 수정 불필요 — 기존 notification_ui가 project 문자열을 그대로 렌더링.

### 5.6 Integration Points

| 컴포넌트 | 변경 사항 |
|----------|----------|
| `daemon.py` | NetworkServer/Client 통합, `_handle_remote_message()`, 세션 스코핑, 포워딩 로직 |
| `socket_server.py` | 변경 없음 (로컬 Unix socket 유지) |
| `protocol.py` | 변경 없음 (메시지 형식 재사용) |
| `transport.py` | 변경 없음 (NetworkClient는 TransportClient 아님) |
| `app.py` | Network 서브메뉴 추가, 모드 전환 UI |
| `preferences.py` | 네트워크 설정 키 추가 |
| `session_store.py` | 원격 세션 저장/복원 (hostname prefix 포함) |
| `notification_ui.c` | 변경 없음 (project 문자열 그대로 표시) |
| `ble_service.c` | 변경 없음 |
| `scene.c` | 변경 없음 |

### 5.7 Preferences 확장

```json
{
  "network_mode": "server",
  "network_port": 19873,
  "network_server_host": "",
  "network_server_port": 19873,
  "network_bonjour_enabled": true
}
```

## 6. Non-Functional Requirements

- **성능**: 원격 클라이언트 10대 이상 동시 연결 지원. 메시지 처리 지연 < 50ms.
- **안정성**: 클라이언트 연결 끊김 시 서버 크래시 없음. 서버 다운 시 클라이언트는 로컬 디스플레이 유지하며 재연결 시도.
- **보안**: LAN trust 모델 (인증 없음). 포트는 기본 0.0.0.0 바인드이므로 방화벽 설정은 사용자 책임.
- **호환성**: 네트워크 모드 비활성 시 기존 동작과 100% 동일. 신규 파일 추가 중심, 기존 코드 최소 변경.

## 7. Auto-Decisions

| Decision | Tier | Rationale |
|----------|------|-----------|
| TCP 포트 19873 | tiny | 시뮬레이터 포트(19872) 바로 다음, 충돌 방지 |
| 뉴라인 구분 JSON 프로토콜 | tiny | Unix socket, 시뮬레이터 TCP와 동일 패턴 |
| 세션 ID 스코핑 `{hostname}:{sid}` | small | 간결하고 충돌 없음. `_session_states` dict 키로 직접 사용 |
| NetworkClient는 TransportClient 미구현 | small | 출력 트랜스포트(BLE/Sim)와 역할이 다름 — 입력 포워더 |
| project 필드에 hostname prefix 삽입 | small | 펌웨어 수정 없이 기존 notification_ui 활용 |
| `network_server.py`, `network_client.py` 신규 파일 | tiny | 기존 파일 비대화 방지, 단일 책임 원칙 |
| 클라이언트 연결 해제 시 세션 즉시 제거 | small | staleness timeout 대기 불필요 — 연결 끊김 = 세션 무효 |
| Bonjour에 pyobjc NSNetServiceBrowser 사용 | small | 메뉴바 앱이 이미 pyobjc 의존, 추가 패키지 불필요 |
| 0.0.0.0 바인드 (모든 인터페이스) | tiny | LAN 내 접근 허용 필수 |
| hello/welcome 핸드셰이크 | small | 최소 식별, 인증 없는 구조에서 hostname 확인 |

## 8. Open Questions

없음 — 모든 medium+ 결정이 사용자 확인 완료.

## 9. Next Step

→ `stv:trace docs/network-mode/spec.md`로 시나리오별 vertical trace 생성
