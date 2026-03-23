# Clawd Tank Network API

TCP `localhost:19873` (JSON over newline-delimited TCP)

## Quick Start

```bash
# 1. Connect + handshake
nc localhost 19873
{"type":"hello","hostname":"my-agent"}
# ← receives: {"type":"welcome","server":"macbook-a"}

# 2. Start session
{"event":"session_start","session_id":"s1","project":"my-project"}

# 3. Show activity
{"event":"tool_use","session_id":"s1","tool_name":"Edit","project":"my-project"}

# 4. Done
{"event":"dismiss","hook":"SessionEnd","session_id":"s1"}
```

## Connection

```
TCP connect → host:19873
Send:    {"type":"hello","hostname":"<your-name>"}\n
Receive: {"type":"welcome","server":"<server-name>"}\n
```

`hostname`은 필수. 서버가 자동으로 라벨 `[A]`, `[B]`, `[C]`... 을 할당하여 알림 카드에 표시.

## Events

### session_start — 세션 시작

```json
{"event":"session_start","session_id":"s1","project":"my-project"}
{"event":"session_start","session_id":"s1","project":"my-project","skin":"clawd-white"}
{"event":"session_start","session_id":"s1","project":"my-project","skin":"clawd-custom","body_color":"FF0000"}
```

| skin | 시각 효과 |
|------|----------|
| `clawd` (기본) | 주황 크랩 |
| `clawd-white` | 밝은 흰색 크랩 |
| `clawd-transparent` | 반투명 유령 크랩 |
| `clawd-black` | 어두운 실루엣 크랩 |
| `clawd-custom` | `body_color` hex로 지정 |

### tool_use — 도구 사용 (크랩 애니메이션 변경)

```json
{"event":"tool_use","session_id":"s1","tool_name":"Edit","project":"my-project"}
```

| tool_name | 크랩 애니메이션 |
|-----------|-------------|
| `Edit`, `Write` | typing (타이핑) |
| `Read`, `Grep`, `Glob` | debugger (돋보기) |
| `Bash` | building (빌딩) |
| `Agent` | conducting (지휘) |
| `WebSearch`, `WebFetch` | wizard (마법사) |
| `LSP`, `mcp__*` | beacon (안테나) |

### add — 알림 카드 표시

```json
{"event":"add","hook":"Stop","session_id":"s1","project":"my-project","message":"Waiting for input"}
```

| hook | 의미 | 크랩 |
|------|------|------|
| `Stop` | 입력 대기 | idle |
| `StopFailure` | 에러 발생 | dizzy + 빨간 LED 3회 |
| `Notification` | idle 알림 | confused |

### dismiss — 알림 해제 / 세션 종료

```json
{"event":"dismiss","hook":"UserPromptSubmit","session_id":"s1"}
{"event":"dismiss","hook":"SessionEnd","session_id":"s1"}
```

| hook | 의미 |
|------|------|
| `UserPromptSubmit` | 사용자 입력 → thinking 상태 |
| `SessionEnd` | 세션 완전 종료 (크랩 퇴장) |

### subagent_start / subagent_stop — 서브에이전트

```json
{"event":"subagent_start","session_id":"s1","agent_id":"agent-1"}
{"event":"subagent_stop","session_id":"s1","agent_id":"agent-1"}
```

HUD에 미니 크랩 + 서브에이전트 카운터 표시.

### compact — 스위핑 애니메이션

```json
{"event":"compact","session_id":"s1"}
```

## Python Example

```python
import asyncio, json

async def main():
    r, w = await asyncio.open_connection("localhost", 19873)

    # Handshake
    w.write(json.dumps({"type":"hello","hostname":"my-bot"}).encode() + b"\n")
    await w.drain()
    welcome = await r.readline()  # {"type":"welcome",...}

    # Session
    def send(msg):
        w.write(json.dumps(msg).encode() + b"\n")

    send({"event":"session_start","session_id":"s1","project":"my-project"})
    send({"event":"tool_use","session_id":"s1","tool_name":"Edit","project":"my-project"})
    await w.drain()
    await asyncio.sleep(5)

    send({"event":"dismiss","hook":"SessionEnd","session_id":"s1"})
    await w.drain()
    w.close()

asyncio.run(main())
```

## Shell One-liner

```bash
(echo '{"type":"hello","hostname":"test"}'; sleep 0.5; \
 echo '{"event":"session_start","session_id":"s1","project":"demo"}'; \
 echo '{"event":"tool_use","session_id":"s1","tool_name":"Bash","project":"demo"}'; \
 sleep 5; \
 echo '{"event":"dismiss","hook":"SessionEnd","session_id":"s1"}') | nc localhost 19873
```

## Notes

- 세션 ID는 클라이언트 내에서 유니크하면 됨 (서버가 `hostname:session_id`로 스코핑)
- 최대 4마리 크랩 동시 표시, 초과 시 `+N` 오버플로 뱃지
- 10분간 이벤트 없는 세션은 자동 제거 (staleness eviction)
- 연결 끊기면 해당 클라이언트의 모든 세션 즉시 제거
