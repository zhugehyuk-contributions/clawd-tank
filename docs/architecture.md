# Clawd Tank Architecture

Claude Code 세션을 물리적 디스플레이에 시각화하는 알림 시스템.
Waveshare ESP32-C6-LCD-1.47 (320×172 ST7789) 위에 픽셀아트 크랩 "Clawd"가 현재 작업 상태를 실시간으로 보여준다.

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  Claude Code                                                     │
│  (hooks: SessionStart, PreToolUse, PreCompact, Stop,            │
│   StopFailure, Notification, UserPromptSubmit, SessionEnd,       │
│   SubagentStart, SubagentStop)                                   │
└──────────┬───────────────────────────────────────────────────────┘
           │ stdin (JSON)
           ▼
┌─────────────────────┐
│  clawd-tank-notify   │  Python, 106줄, stdlib only
│  (hook handler)      │  ~/.clawd-tank/clawd-tank-notify
└──────────┬──────────┘
           │ Unix socket (~/.clawd-tank/sock)
           ▼
┌──────────────────────────────────────────────────────────┐
│  ClawdDaemon (asyncio)                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ SocketServer │  │ SessionState │  │ TransportMgr  │  │
│  │ (Unix sock)  │→ │ (per-session │→ │ (BLE + TCP)   │  │
│  └──────────────┘  │  tracking)   │  └──┬─────┬──────┘  │
│                     └──────────────┘     │     │         │
└──────────────────────────────────────────┼─────┼─────────┘
                                           │     │
              BLE GATT write ──────────────┘     └──── TCP JSON
              (256B MTU)                               (port 19872)
           ▼                                        ▼
┌─────────────────────┐               ┌─────────────────────┐
│  ESP32-C6 Firmware   │               │  Simulator (SDL2)    │
│  320×172 ST7789      │               │  동일 펌웨어 소스     │
│  NimBLE GATT server  │               │  + shims/ 레이어     │
│  LVGL 9.5 UI         │               │  macOS .app 번들     │
└─────────────────────┘               └─────────────────────┘
```

## Components

### 1. Hook Handler — `clawd-tank-notify`

| 항목 | 값 |
|------|---|
| 경로 | `~/.clawd-tank/clawd-tank-notify` (메뉴바 앱이 자동 설치) |
| 소스 | `host/clawd-tank-notify` (106줄) |
| 의존성 | Python stdlib only — 외부 패키지 없음 |

Claude Code hooks 설정에 등록되어, 모든 hook 이벤트마다 실행된다.

**동작 흐름:**
1. stdin에서 Claude Code hook JSON 읽기
2. `protocol.hook_payload_to_daemon_message()`로 daemon 메시지로 변환
3. Unix socket으로 daemon에 전달
4. daemon이 없으면 자동 시작 (5초 대기)

**설계 원칙:** hook handler는 Claude Code의 응답 지연에 직접 영향을 주므로 가능한 빠르게 실행해야 한다. 외부 패키지 import 없이 stdlib만 사용. 알림은 best-effort — 전송 실패 시 exit 0으로 조용히 종료.

### 2. Daemon — `clawd_tank_daemon/`

| 파일 | 줄수 | 역할 |
|------|------|------|
| `daemon.py` | 667 | 핵심 로직: 세션 추적, 디스플레이 상태 계산, 트랜스포트 관리 |
| `protocol.py` | 170 | 3단계 메시지 변환 (hook → daemon → BLE/TCP) |
| `transport.py` | 24 | `TransportClient` Protocol 인터페이스 |
| `ble_client.py` | 148 | BLE GATT 클라이언트 (bleak) |
| `sim_client.py` | 159 | TCP 시뮬레이터 클라이언트 |
| `sim_process.py` | 156 | 시뮬레이터 프로세스 라이프사이클 관리 |
| `socket_server.py` | ~80 | Unix socket 수신 서버 |
| `session_store.py` | 106 | 세션 상태 영속화 (JSON) |

#### 2.1 세션 상태 머신

```
                ┌─── SessionStart ───┐
                ▼                    │
           registered                │
                │                    │
                ├── UserPromptSubmit ─┤
                ▼                    │
            thinking                 │
                │                    │
                ├── PreToolUse ──────┤
                ▼                    │
            working ◄───┐            │
                │       │            │
                │   PreToolUse       │
                │   (tool change)    │
                │       │            │
                ├───────┘            │
                │                    │
        ┌───────┼────────────┐       │
        ▼       ▼            ▼       │
      idle   confused     error      │
    (Stop)  (Notification) (StopFailure)
        │       │            │       │
        └───────┴────────────┘       │
                │                    │
                ├── UserPromptSubmit → thinking (재진입)
                │
                └── SessionEnd → 제거
                └── timeout (10min) → 제거 (staleness eviction)
```

각 세션은 `session_id`로 식별되며, `_session_states` dict에 상태(`state`), 마지막 이벤트 시각(`last_event`), 도구 이름(`tool_name`), 서브에이전트 집합(`subagents`)을 추적한다.

#### 2.2 디스플레이 상태 계산

`_compute_display_state()`가 모든 세션 상태를 집계하여 디바이스에 보낼 디스플레이 상태를 결정:

```python
# 세션이 없으면 → sleeping
# 최대 4개 세션의 애니메이션 + 고유 ID 생성
# 서브에이전트 합산, overflow 계산
→ {"anims": ["typing", "thinking"], "ids": [1, 2], "subagents": 3, "overflow": 2}
```

**도구 → 애니메이션 매핑:**

| 도구 | 애니메이션 | 시각적 의미 |
|------|-----------|------------|
| `Edit`, `Write`, `NotebookEdit` | typing | 타이핑하는 크랩 |
| `Read`, `Grep`, `Glob` | debugger | 돋보기 들고 탐색 |
| `Bash` | building | 빌딩/건설 |
| `Agent` | conducting | 지휘자처럼 팔 흔들기 |
| `WebSearch`, `WebFetch` | wizard | 마법 지팡이 + 스파클 |
| `LSP`, `mcp__*` | beacon | 안테나에서 전파 발사 |

#### 2.3 멀티 트랜스포트 아키텍처

```
TransportClient (Protocol)
    ├── ClawdBleClient   BLE GATT write, bleak 라이브러리
    └── SimClient        TCP JSON, asyncio streams
```

각 트랜스포트는 독립 큐와 sender 태스크를 가짐. 런타임에 동적 추가/제거 가능. 프로토콜 버전별 분기:

- **v2** (`set_sessions`): 세션별 개별 애니메이션 + 고유 ID. 멀티 크랩 동시 표시.
- **v1** (`set_status`): 단일 집계 상태. `working_1` (1세션=Typing), `working_2` (2세션=Juggling), `working_3` (3+세션=Building).

시뮬레이터는 항상 v2. BLE는 연결 시 버전 GATT 특성을 읽어 결정.

#### 2.4 세션 영속화

`session_store.py`가 `~/.clawd-tank/sessions.json`에 세션 상태를 원자적으로 저장. 구조적 변경(상태 전이, 서브에이전트 변경) 시마다 저장. 데몬 재시작 시 로드하여 stale 세션 즉시 제거.

### 3. 프로토콜 — `protocol.py`

3단계 변환 파이프라인:

```
Claude Code Hook JSON
        │
        ▼  hook_payload_to_daemon_message()
Daemon Message (internal)
        │
        ├──▶ daemon_message_to_ble_payload()     → add/dismiss/clear 알림
        ├──▶ display_state_to_ble_payload()      → v2 set_sessions
        └──▶ display_state_to_v1_payload()       → v1 set_status (레거시)
```

**Hook 이벤트 → Daemon 메시지 매핑:**

| Hook Event | Daemon Event | 세션 상태 전이 |
|------------|-------------|---------------|
| `SessionStart` | `session_start` | → registered |
| `PreToolUse` | `tool_use` | → working |
| `PreCompact` | `compact` | sweeping oneshot |
| `Stop` | `add` | → idle |
| `StopFailure` | `add` (alert=error) | → error |
| `Notification` (idle_prompt) | `add` | → confused |
| `UserPromptSubmit` | `dismiss` | → thinking |
| `SessionEnd` | `dismiss` | 제거 |
| `SubagentStart` | `subagent_start` | subagents += agent_id |
| `SubagentStop` | `subagent_stop` | subagents -= agent_id |

### 4. Firmware — `firmware/main/`

| 파일 | 줄수 | 역할 |
|------|------|------|
| `main.c` | 74 | 진입점, FreeRTOS 큐, 초기화, UI 태스크 생성 |
| `ble_service.c` | 412 | NimBLE GATT 서버, JSON 파싱, 이벤트 큐 포스트 |
| `ui_manager.c` | 343 | 상태 머신 (FULL_IDLE / NOTIFICATION / DISCONNECTED) |
| `scene.c` | 1,483 | 스프라이트 애니메이션 엔진, 멀티슬롯 렌더링 |
| `notification_ui.c` | 501 | LVGL 알림 카드 UI |
| `notification.c` | 106 | 링 버퍼 스토어 (최대 8개) |
| `display.c` | 188 | SPI + ST7789 + LVGL + PWM 백라이트 |
| `pixel_font.c` | 157 | 비트맵 폰트 (HUD 오버레이) |
| `rgb_led.c` | 180 | WS2812B RGB LED 플래시 |
| `config_store.c` | 86 | NVS 설정 저장 (밝기) |
| `rle_sprite.h` | 104 | RLE 압축 스프라이트 디코더 |

#### 4.1 실행 흐름

```
app_main()
    ├── nvs_flash_init()
    ├── config_store_init()          NVS에서 밝기 로드
    ├── display_init()               SPI + ST7789 + LVGL + 백라이트
    ├── ble_service_init(queue)      NimBLE GATT 서버 시작
    ├── button_init(queue)           BOOT 버튼 (GPIO0)
    └── xTaskCreate(ui_task)         5ms 주기 루프
            │
            ├── xQueueReceive()      BLE 이벤트 수신
            │   └── ui_manager_handle_event()
            └── ui_manager_tick()
                ├── scene_tick()     스프라이트 프레임 어드밴스
                ├── time update      시계 갱신 (분 단위)
                └── lv_timer_handler()  LVGL 렌더링
```

#### 4.2 BLE GATT 구조

| UUID | 타입 | 설명 |
|------|------|------|
| `AECBEFD9-...` | Service | Clawd Tank 서비스 |
| `71FFB137-...` | Write | 알림/상태 JSON (add, dismiss, clear, set_status, set_sessions, set_time) |
| `E9F6E626-...` | Read/Write | 설정 (밝기) |
| `B6DC9A5B-...` | Read | 프로토콜 버전 ("2") |

JSON 페이로드 예시:
```json
{"action": "add", "id": "sess123", "project": "clawd-tank", "message": "Waiting for input"}
{"action": "set_sessions", "anims": ["typing","debugger"], "ids": [1,2], "subagents": 1}
{"action": "set_status", "status": "sleeping"}
{"action": "set_time", "epoch": 1711180800, "tz": "KST-9"}
```

#### 4.3 UI 상태 머신

```
                    BLE_EVT_CONNECTED
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────────┐
    │ FULL_IDLE │◄──│ NOTIFI-  │    │ DISCONNECTED │
    │ 320px    │──►│ CATION   │    │  320px       │
    │ 시계 표시 │    │ 107px    │    │  DISCONN 애님│
    └──────────┘    │ 카드 표시 │    └──────────────┘
                    └──────────┘           ▲
                                           │
                                    BLE_EVT_DISCONNECTED
```

- **FULL_IDLE**: 씬이 전체 너비(320px). 시계 표시. 크랩이 현재 상태 애니메이션 재생.
- **NOTIFICATION**: 씬이 107px로 좁아지고, 오른쪽에 알림 카드 패널 표시. 크랩은 ALERT 재생.
- **DISCONNECTED**: 전체 너비, DISCONNECTED 애니메이션. 시계 숨김.

#### 4.4 Scene 엔진 (`scene.c`)

프로젝트에서 가장 큰 파일 (1,483줄). 핵심 개념:

**19개 애니메이션:**
IDLE, ALERT, HAPPY, SLEEPING, DISCONNECTED, THINKING, TYPING, JUGGLING, BUILDING, CONFUSED, DIZZY, SWEEPING, GOING_AWAY, WALKING, DEBUGGER, WIZARD, CONDUCTING, BEACON, MINI_CLAWD

**멀티슬롯 렌더링:**
- `MAX_VISIBLE = 4`: 동시에 최대 4마리 크랩 표시
- `MAX_SLOTS = 6` (firmware) / `8` (simulator): 퇴장 애니메이션용 여분 슬롯
- 각 슬롯은 독립적 애니메이션, 위치, 프레임 버퍼를 가짐

**세션 전환 애니메이션:**
- **Walk-in**: 새 세션이 화면 오른쪽에서 걸어 들어옴
- **Going-away**: 종료 세션이 바닥으로 파고 들어감 (burrowing)
- 퇴장 후 남은 크랩들이 재배치 (walk animation)

**배경 레이어:**
- 그라디언트 하늘 (상단 어두운 남색 → 하단 밝은 남색)
- 반짝이는 별 6개 (2~4초 랜덤 주기)
- 잔디 바 (하단 14px)

**HUD 오버레이:**
- 서브에이전트 카운터: 미니 크랩 아이콘 + 숫자 (pixel_font)
- 오버플로 뱃지: "+N" (4개 초과 세션)

**스프라이트 포맷:**
- RLE 압축 RGB565 배열 + 투명 키 `0x18C5`
- 펌웨어: RGB565A8 (3바이트/픽셀)로 디코딩
- 시뮬레이터: ARGB8888 (4바이트/픽셀)
- 슬롯당 프레임 버퍼 lazy allocation

### 5. Simulator — `simulator/`

| 파일 | 줄수 | 역할 |
|------|------|------|
| `sim_main.c` | 547 | SDL2 윈도우, 이벤트 루프, 키보드, 스크린샷 |
| `sim_display.c` | 375 | SDL2 렌더러, LVGL 디스플레이 드라이버 |
| `sim_socket.c` | 389 | TCP 리스너, 링버퍼, 양방향 이벤트 |
| `sim_ble_parse.c` | 154 | JSON 파서 (펌웨어 미러) |
| `sim_events.c` | 385 | 인라인 이벤트 파서, 시나리오 파일 |
| `sim_timer.c` | ~50 | 타이머 shim |
| `shims/` | — | ESP-IDF API 대체 헤더 (freertos, esp_log 등) |

**핵심 설계:** 펌웨어 C 소스(`scene.c`, `notification_ui.c`, `ui_manager.c` 등)를 **수정 없이** 시뮬레이터에서 컴파일. ESP-IDF API는 `shims/` 디렉토리의 빈 헤더로 대체.

**빌드 모드:**
- **Dynamic SDL2**: 개발용, Homebrew SDL2 링크
- **Static SDL2**: 배포용, FetchContent로 SDL2를 빌드에 포함 (외부 의존성 없음)

**실행 모드:**
```
Interactive (SDL2 윈도우)     + --listen (TCP 서버)
Headless (--headless)        + --events '...' 또는 시나리오 파일
```

**TCP 프로토콜** (port 19872):
- 인바운드: BLE와 동일한 JSON + 윈도우 명령 (`show_window`, `hide_window`, `set_window`, `query_state`)
- 아웃바운드: `{"event":"window_hidden"}` — 사용자가 윈도우를 닫았을 때

### 6. Menu Bar App — `clawd_tank_menubar/`

| 파일 | 줄수 | 역할 |
|------|------|------|
| `app.py` | 535 | macOS 상태바 앱 (rumps), 트랜스포트 서브메뉴 |
| `hooks.py` | 226 | Claude Code hook 설치/업데이트 |
| `slider.py` | 97 | 밝기 슬라이더 UI |
| `version.py` | 88 | 버전 관리 |
| `launchd.py` | 69 | 자동 시작 설정 |
| `preferences.py` | ~50 | `~/.clawd-tank/preferences.json` 관리 |

**기능:**
- BLE / Simulator 트랜스포트 독립 on/off
- 연결 상태 컬러 이모지 표시
- 시뮬레이터 윈도우 show/hide, always-on-top
- 밝기 / 세션 타임아웃 설정
- Claude Code hook 자동 설치 및 업데이트
- 데몬 스레드 health check (크래시 감지)

**구조:**
```
ClawdTankApp (rumps.App + DaemonObserver)
    ├── daemon thread (asyncio event loop)
    │   └── ClawdDaemon
    │       ├── SocketServer
    │       ├── BLE transport
    │       └── Sim transport
    │           └── SimProcessManager (시뮬레이터 서브프로세스)
    └── main thread (rumps UI)
```

### 7. Sprite Pipeline — `tools/`

```
Animated SVG
    │  svg2frames.py (Playwright 렌더링)
    ▼
PNG Frame Sequence (e.g. frame_000.png ... frame_023.png)
    │  png2rgb565.py (RGB565 변환 + RLE 압축)
    ▼
C Header (e.g. sprite_typing.h)
    │  crop_sprites.py (대칭 크롭, 중심 유지)
    ▼
최적화된 C Header (firmware/main/assets/)
```

## Hardware Constraints

| 항목 | 제한 |
|------|------|
| 디스플레이 | 320×172 px, 16-bit RGB565, SPI |
| 칩 | ESP32-C6FH8 (RISC-V, single core) |
| 메모리 | 8MB flash, 512KB SRAM (~200KB free) |
| BLE MTU | 256 bytes |
| 알림 | 최대 8개 (ring buffer) |
| LVGL | v9.5.0 |
| RGB LED | WS2812B on GPIO8 |
| 시간 | WiFi/NTP 없음 — 호스트가 BLE로 동기화 |

## File Layout

```
clawd-tank/
├── firmware/
│   ├── main/
│   │   ├── main.c              진입점
│   │   ├── ble_service.c/h     BLE GATT 서버
│   │   ├── ui_manager.c/h      UI 상태 머신
│   │   ├── scene.c/h           스프라이트 엔진
│   │   ├── notification_ui.c/h LVGL 카드 UI
│   │   ├── notification.c/h    링 버퍼 스토어
│   │   ├── display.c/h         SPI + ST7789 + LVGL
│   │   ├── pixel_font.c/h      비트맵 폰트
│   │   ├── rgb_led.c/h         WS2812B 드라이버
│   │   ├── config_store.c/h    NVS 설정
│   │   ├── button.c/h          BOOT 버튼
│   │   ├── rle_sprite.h        RLE 디코더
│   │   └── assets/             스프라이트 C 헤더 (21개)
│   ├── CMakeLists.txt
│   ├── sdkconfig.defaults
│   └── partitions.csv
├── simulator/
│   ├── sim_main.c              SDL2 진입점
│   ├── sim_display.c/h         SDL2 렌더러
│   ├── sim_socket.c/h          TCP 리스너
│   ├── sim_ble_parse.c/h       JSON 파서
│   ├── sim_events.c/h          이벤트 파서
│   ├── sim_timer.c/h           타이머 shim
│   ├── sim_screenshot.c/h      PNG 캡처
│   ├── shims/                  ESP-IDF API 대체
│   ├── cjson/                  cJSON 라이브러리
│   ├── lv_conf.h               시뮬레이터용 LVGL 설정
│   └── CMakeLists.txt
├── host/
│   ├── clawd-tank-notify       Hook handler (stdlib only)
│   ├── clawd_tank_daemon/
│   │   ├── daemon.py           핵심 데몬
│   │   ├── protocol.py         메시지 변환
│   │   ├── transport.py        TransportClient Protocol
│   │   ├── ble_client.py       BLE 트랜스포트
│   │   ├── sim_client.py       TCP 트랜스포트
│   │   ├── sim_process.py      시뮬레이터 프로세스 관리
│   │   ├── socket_server.py    Unix socket 서버
│   │   └── session_store.py    세션 영속화
│   ├── clawd_tank_menubar/
│   │   ├── app.py              macOS 상태바 앱
│   │   ├── hooks.py            Claude Code hook 설치
│   │   ├── preferences.py      설정 파일 관리
│   │   ├── slider.py           밝기 슬라이더
│   │   ├── version.py          버전 관리
│   │   └── launchd.py          자동 시작
│   ├── build.sh                .app 번들 빌드
│   └── setup.py                py2app 설정
├── tools/
│   ├── svg2frames.py           SVG → PNG 프레임
│   ├── png2rgb565.py           PNG → RLE RGB565 C 헤더
│   ├── crop_sprites.py         스프라이트 크롭
│   ├── analyze_sprite_bounds.py 바운딩박스 분석
│   └── ble_interactive.py      BLE 디버깅 도구
└── docs/
    ├── architecture.md          ← 이 문서
    └── protocol-changelog.md    프로토콜 버전 이력
```

## Key Design Decisions

### 펌웨어 소스 공유
시뮬레이터가 펌웨어 C 소스를 그대로 컴파일한다. `#ifdef SIMULATOR`로 분기하는 경우는 최소화하고, ESP-IDF API는 shim 헤더로 대체. 이로써 시뮬레이터와 실제 디바이스의 렌더링이 픽셀 단위로 동일하다.

### 프로토콜 버전 협상
BLE 연결 시 버전 GATT 특성을 읽어 v1/v2를 결정. 시뮬레이터는 항상 v2. 이로써 구형 펌웨어와도 호환되고, 새 기능(멀티세션)은 v2에서만 활성화.

### 세션 추적과 영속화
데몬이 세션 상태를 메모리에 추적하고, 구조적 변경마다 JSON으로 영속화. 데몬/앱 재시작 시 복원하되 stale 세션은 즉시 제거. 이로써 메뉴바 앱을 껐다 켜도 현재 활성 Claude Code 세션이 올바르게 표시된다.

### Best-effort 알림
hook handler → daemon 통신이 실패해도 Claude Code에 에러를 전파하지 않는다 (exit 0). 알림은 편의 기능이므로 코딩 워크플로우를 방해하지 않아야 한다.

### Static SDL2 빌드
배포용 시뮬레이터는 SDL2를 FetchContent로 정적 링크하여 외부 의존성이 없다. `.app` 번들 안에 바이너리를 포함하여 Homebrew 설치 없이 동작.
