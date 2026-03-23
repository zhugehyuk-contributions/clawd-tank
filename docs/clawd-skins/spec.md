# Clawd Skins — Spec

> STV Spec | Created: 2026-03-23

## 1. Overview

세션 시작 시 `skin` 파라미터로 크랩의 외형을 지정하여, 다른 머신/에이전트를 시각적으로 구분한다. LVGL의 image recolor 기능을 활용하여 펌웨어에 별도 스프라이트 에셋 추가 없이 런타임 색상 변환으로 구현.

## 2. User Stories

- **US-1**: 개발자로서, 원격 머신 A의 세션은 기본 주황 크랩, 머신 B는 흰 크랩, 머신 C는 검정 크랩으로 보고 싶다.
- **US-2**: 개발자로서, 커스텀 색상(예: 빨간 몸체 + 파란 눈)의 크랩을 지정하고 싶다.
- **US-3**: 개발자로서, TCP API로 세션을 만들 때 skin을 지정하여 자동으로 해당 외형이 적용되길 원한다.

## 3. Acceptance Criteria

- [ ] `session_start` 이벤트에 `skin` 필드 지원 (기본값: `"clawd"`)
- [ ] 5가지 프리셋 스킨: `clawd`, `clawd-white`, `clawd-transparent`, `clawd-black`, `clawd-custom`
- [ ] `clawd-custom` 시 `body_color` (hex), `eye_color` (hex) 옵션
- [ ] 스킨 정보가 `set_sessions` 프로토콜로 디바이스/시뮬레이터에 전달
- [ ] 펌웨어/시뮬레이터에서 LVGL recolor로 해당 색상 적용
- [ ] 같은 세션의 모든 애니메이션(idle→typing→building 등)에 일관된 스킨 적용
- [ ] 기존 세션(skin 미지정)은 기본 주황 크랩으로 동작 (하위호환)
- [ ] 멀티슬롯에서 슬롯별 독립 스킨

## 4. Scope

### In-Scope
- 5가지 스킨 프리셋 + custom
- LVGL recolor 기반 색상 변환 (추가 에셋 0)
- TCP/BLE 프로토콜 확장
- daemon/scene.c 통합
- tcp_test.py에 스킨 명령 추가

### Out-of-Scope
- 별도 스프라이트 세트 (플래시 제약)
- 픽셀 단위 HSV 변환 (CPU 비용)
- 눈 색상 분리 렌더링 (눈과 몸체가 같은 스프라이트 데이터)
- 메뉴바 앱에서 스킨 설정 UI

## 5. Architecture

### 5.1 스킨 정의

```
Skin = (recolor: uint32_t hex, recolor_opa: uint8_t 0-255, alpha_opa: uint8_t 0-255)
```

| Skin | recolor | recolor_opa | alpha_opa | 시각 효과 |
|------|---------|-------------|-----------|----------|
| `clawd` | — | 0 | 255 | 기본 주황 (변환 없음) |
| `clawd-white` | `0xFFFFFF` | 180 | 255 | 밝은 흰색 크랩 |
| `clawd-transparent` | — | 0 | 120 | 반투명 유령 크랩 |
| `clawd-black` | `0x000000` | 200 | 255 | 어두운 실루엣 크랩 |
| `clawd-custom` | `{body_color}` | 160 | 255 | 사용자 지정 색상 |

### 5.2 프로토콜 확장

#### session_start (daemon message, 신규 필드)

```json
{"event":"session_start", "session_id":"s1", "project":"proj", "skin":"clawd-white"}
{"event":"session_start", "session_id":"s1", "project":"proj", "skin":"clawd-custom", "body_color":"FF0000"}
```

#### set_sessions (BLE/TCP payload, 신규 필드)

```json
{
  "action": "set_sessions",
  "anims": ["typing", "building"],
  "ids": [1, 2],
  "skins": [0, 1],
  "subagents": 0
}
```

`skins`는 정수 배열 (프리셋 인덱스 또는 커스텀 색상 인코딩):

| 값 | 스킨 |
|---|------|
| 0 | clawd (기본) |
| 1 | clawd-white |
| 2 | clawd-transparent |
| 3 | clawd-black |
| 4+ | clawd-custom (별도 필드로 색상 전달) |

커스텀 색상 전달:
```json
{
  "action": "set_sessions",
  "anims": ["typing"],
  "ids": [1],
  "skins": [4],
  "skin_colors": ["FF0000"],
  "subagents": 0
}
```

### 5.3 데이터 흐름

```
TCP/Hook: session_start(skin="clawd-white")
    ↓
Daemon: _session_states[sid]["skin"] = "clawd-white"
    ↓
Daemon: _compute_display_state() → skins=[1, 0, 3, ...]
    ↓
BLE/TCP: set_sessions(anims=[...], skins=[1, 0, 3, ...])
    ↓
Firmware: ble_service.c → BLE_EVT_SET_SESSIONS에 skin 배열 추가
    ↓
scene.c: scene_set_sessions() → 슬롯별 recolor 적용
    ↓
LVGL: lv_obj_set_style_image_recolor(slot->sprite_img, color, opa)
```

### 5.4 Component Changes

| 컴포넌트 | 변경 |
|----------|------|
| `daemon.py` | `_session_states`에 skin 저장, `_compute_display_state`에 skins 배열 추가 |
| `protocol.py` | `display_state_to_ble_payload`에 skins 필드 |
| `network_server.py` | 변경 없음 (daemon message 그대로 전달) |
| `ble_service.c` | set_sessions 파싱에 skins/skin_colors 추가 |
| `ble_service.h` | `ble_evt_t`에 skin 배열 필드 추가 |
| `scene.h` | skin 관련 enum/struct |
| `scene.c` | `decode_and_apply_frame()` 또는 슬롯 업데이트 시 recolor 적용 |
| `sim_ble_parse.c` | set_sessions 파싱에 skins 추가 |
| `tcp_test.py` | `s` 명령에 skin 옵션, `demo2`에 스킨 다양화 |

### 5.5 Firmware Scene Integration

scene.c의 `clawd_slot_t`에 스킨 정보 추가:

```c
typedef struct {
    // ... existing fields ...
    uint8_t skin_id;          // 0=default, 1=white, 2=transparent, 3=black, 4=custom
    uint32_t skin_color;      // custom body color (RGB888)
} clawd_slot_t;
```

`scene_set_sessions()`에서 슬롯 업데이트 시:

```c
// 슬롯에 skin 적용
switch (slot->skin_id) {
    case 0: // clawd — no recolor
        lv_obj_set_style_image_recolor_opa(img, LV_OPA_TRANSP, 0);
        lv_obj_set_style_opa(img, LV_OPA_COVER, 0);
        break;
    case 1: // clawd-white
        lv_obj_set_style_image_recolor(img, lv_color_hex(0xFFFFFF), 0);
        lv_obj_set_style_image_recolor_opa(img, LV_OPA_70, 0);
        break;
    case 2: // clawd-transparent
        lv_obj_set_style_opa(img, LV_OPA_50, 0);
        break;
    case 3: // clawd-black
        lv_obj_set_style_image_recolor(img, lv_color_hex(0x000000), 0);
        lv_obj_set_style_image_recolor_opa(img, LV_OPA_80, 0);
        break;
    case 4: // clawd-custom
        lv_obj_set_style_image_recolor(img, lv_color_hex(slot->skin_color), 0);
        lv_obj_set_style_image_recolor_opa(img, LV_OPA_60, 0);
        break;
}
```

## 6. Non-Functional Requirements

- **성능**: recolor는 LVGL 렌더러가 처리, CPU 오버헤드 무시 가능
- **메모리**: 슬롯당 +5 bytes (skin_id + skin_color), 추가 에셋 0
- **호환성**: skins 필드 없는 set_sessions → 기본 스킨 (하위호환)

## 7. Auto-Decisions

| Decision | Tier | Rationale |
|----------|------|-----------|
| LVGL recolor 방식 채택 | small | 이미 DISCONNECTED에서 사용 중, 추가 에셋/메모리 0 |
| 스킨 인덱스는 정수 (0-4) | tiny | BLE MTU 절약, 문자열 대비 효율적 |
| eye_color는 Out-of-Scope | small | 눈과 몸체가 같은 스프라이트 데이터, 분리 불가 |
| recolor_opa 값은 하드코딩 | tiny | 프리셋별 최적값 실험 후 고정 |
| skin 정보는 session_states에 저장 | small | 기존 세션 추적 구조 재활용 |

## 8. Open Questions

없음.

## 9. Next Step

→ `stv:trace docs/clawd-skins/spec.md`로 시나리오별 vertical trace 생성
