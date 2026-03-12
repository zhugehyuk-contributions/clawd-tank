// firmware/main/ui_manager.c
#include "ui_manager.h"
#include "scene.h"
#include "notification_ui.h"
#include "notification.h"
#include "config_store.h"
#include "esp_log.h"
#include <stdio.h>
#include <time.h>
#include <sys/time.h>

static const char *TAG = "ui";

/* ---------- State machine ---------- */

typedef enum {
    UI_STATE_FULL_IDLE,
    UI_STATE_NOTIFICATION,
    UI_STATE_DISCONNECTED,
} ui_state_t;

#define SCENE_FULL_WIDTH   320
#define SCENE_NOTIF_WIDTH  107
#define SCENE_ANIM_MS      400

static uint32_t s_sleep_timeout_ms = 5 * 60 * 1000;  /* updated by config store */

/* ---------- Module state ---------- */

static ui_state_t s_state = UI_STATE_DISCONNECTED;
static notification_store_t s_store;
static _lock_t s_lock;

static scene_t *s_scene = NULL;
static notification_ui_t *s_notif_ui = NULL;

static bool s_connected = false;
static uint32_t s_last_activity_tick = 0;
static bool s_sleeping = false;
static int s_last_minute = -1;

static void scene_animate_width(int target_px, int anim_ms)
{
    if (!s_scene) return;

    /* Get the container from scene for animation */
    /* Use scene_set_width for instant, but for animated we need the callback */
    if (anim_ms <= 0) {
        scene_set_width(s_scene, target_px, 0);
        if (s_notif_ui) {
            notification_ui_set_x(s_notif_ui, target_px);
        }
        return;
    }

    scene_set_width(s_scene, target_px, anim_ms);
    /* notification_ui tracks via scene_set_width's own animation —
       for simplicity, just set the final x immediately.
       The visual gap is small at 400ms. */
    if (s_notif_ui) {
        notification_ui_set_x(s_notif_ui, target_px);
    }
}

/* ---------- Transition ---------- */

static void transition_to(ui_state_t new_state)
{
    if (new_state == s_state) return;

    ui_state_t old_state = s_state;
    s_state = new_state;

    switch (new_state) {
    case UI_STATE_FULL_IDLE:
        scene_animate_width(SCENE_FULL_WIDTH, SCENE_ANIM_MS);
        notification_ui_show(s_notif_ui, false, 0);
        scene_set_ble_icon_visible(s_scene, false);
        scene_set_time_visible(s_scene, true);

        /* Don't overwrite a oneshot animation (happy/alert) */
        if (!scene_is_playing_oneshot(s_scene)) {
            scene_set_clawd_anim(s_scene, CLAWD_ANIM_IDLE);
        }

        s_sleeping = false;
        s_last_activity_tick = lv_tick_get();
        break;

    case UI_STATE_NOTIFICATION:
        scene_animate_width(SCENE_NOTIF_WIDTH,
                            old_state == UI_STATE_FULL_IDLE ? SCENE_ANIM_MS : 0);
        notification_ui_show(s_notif_ui, true, 300);
        scene_set_ble_icon_visible(s_scene, false);
        scene_set_time_visible(s_scene, false);
        scene_set_clawd_anim(s_scene, CLAWD_ANIM_ALERT);

        s_sleeping = false;
        s_last_activity_tick = lv_tick_get();
        break;

    case UI_STATE_DISCONNECTED:
        scene_animate_width(SCENE_FULL_WIDTH, SCENE_ANIM_MS);
        notification_ui_show(s_notif_ui, false, 0);
        scene_set_ble_icon_visible(s_scene, true);
        scene_set_time_visible(s_scene, false);
        scene_set_clawd_anim(s_scene, CLAWD_ANIM_DISCONNECTED);

        s_sleeping = false;
        break;
    }
}

/* ---------- Init ---------- */

void ui_manager_init(void)
{
    _lock_init(&s_lock);
    s_sleep_timeout_ms = config_store_get_sleep_timeout_ms();
    notif_store_init(&s_store);

    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x0f1320), 0);

    /* Create scene (left panel — starts full width) */
    s_scene = scene_create(screen);
    scene_set_width(s_scene, SCENE_FULL_WIDTH, 0);
    scene_set_clawd_anim(s_scene, CLAWD_ANIM_DISCONNECTED);
    scene_set_ble_icon_visible(s_scene, true);

    /* Create notification UI (right panel — starts hidden) */
    s_notif_ui = notification_ui_create(screen);

    s_state = UI_STATE_DISCONNECTED;
    s_connected = false;
    s_last_activity_tick = lv_tick_get();
    s_last_minute = -1;

    ESP_LOGI(TAG, "UI manager initialized with scene + notification panel");
}

/* ---------- Event handling ---------- */

void ui_manager_handle_event(const ble_evt_t *evt)
{
    _lock_acquire(&s_lock);

    switch (evt->type) {
    case BLE_EVT_CONNECTED:
        ESP_LOGI(TAG, "Connected");
        s_connected = true;
        /* Happy reaction on reconnect per spec */
        scene_set_clawd_anim(s_scene, CLAWD_ANIM_HAPPY);
        /* Transition based on notification count */
        if (notif_store_count(&s_store) > 0) {
            transition_to(UI_STATE_NOTIFICATION);
        } else {
            transition_to(UI_STATE_FULL_IDLE);
        }
        break;

    case BLE_EVT_DISCONNECTED:
        ESP_LOGI(TAG, "Disconnected");
        s_connected = false;
        notif_store_clear(&s_store);
        transition_to(UI_STATE_DISCONNECTED);
        break;

    case BLE_EVT_NOTIF_ADD:
        ESP_LOGI(TAG, "Add: %s (%s)", evt->id, evt->project);
        notif_store_add(&s_store, evt->id, evt->project, evt->message);
        notification_ui_rebuild(s_notif_ui, &s_store);

        if (s_state != UI_STATE_NOTIFICATION) {
            transition_to(UI_STATE_NOTIFICATION);
        } else {
            /* Already in notification view — just play alert */
            scene_set_clawd_anim(s_scene, CLAWD_ANIM_ALERT);
        }
        s_last_activity_tick = lv_tick_get();
        break;

    case BLE_EVT_NOTIF_DISMISS:
        ESP_LOGI(TAG, "Dismiss: %s", evt->id);
        notif_store_dismiss(&s_store, evt->id);

        if (notif_store_count(&s_store) == 0) {
            /* Last notification cleared — happy then idle */
            scene_set_clawd_anim(s_scene, CLAWD_ANIM_HAPPY);
            transition_to(UI_STATE_FULL_IDLE);
        } else {
            notification_ui_rebuild(s_notif_ui, &s_store);
        }
        s_last_activity_tick = lv_tick_get();
        break;

    case BLE_EVT_NOTIF_CLEAR:
        ESP_LOGI(TAG, "Clear all");
        notif_store_clear(&s_store);
        scene_set_clawd_anim(s_scene, CLAWD_ANIM_HAPPY);
        transition_to(UI_STATE_FULL_IDLE);
        s_last_activity_tick = lv_tick_get();
        break;
    }

    _lock_release(&s_lock);
}

/* ---------- Tick ---------- */

void ui_manager_tick(void)
{
    _lock_acquire(&s_lock);

    /* Scene animation tick (sprite frame advance, star twinkle) */
    scene_tick(s_scene);

    /* Sleep timeout: 5 minutes of idle while connected */
    if (s_state == UI_STATE_FULL_IDLE && s_connected && !s_sleeping) {
        uint32_t elapsed = lv_tick_get() - s_last_activity_tick;
        if (s_sleep_timeout_ms > 0 && elapsed >= s_sleep_timeout_ms) {
            scene_set_clawd_anim(s_scene, CLAWD_ANIM_SLEEPING);
            s_sleeping = true;
            ESP_LOGI(TAG, "Clawd falling asleep (5m idle)");
        }
    }

    /* Time update: check once per tick, update when minute changes */
    if (s_state == UI_STATE_FULL_IDLE) {
        struct timeval tv;
        gettimeofday(&tv, NULL);
        struct tm tm;
        localtime_r(&tv.tv_sec, &tm);
        int cur_minute = tm.tm_hour * 60 + tm.tm_min;
        if (cur_minute != s_last_minute) {
            s_last_minute = cur_minute;
            scene_update_time(s_scene, tm.tm_hour, tm.tm_min);
        }
    }

    /* LVGL timer handler */
    lv_timer_handler();

    _lock_release(&s_lock);
}

void ui_manager_set_sleep_timeout(uint32_t ms)
{
    _lock_acquire(&s_lock);
    s_sleep_timeout_ms = ms;
    s_last_activity_tick = lv_tick_get();  /* reset idle timer */
    if (s_sleeping) {
        s_sleeping = false;
        if (s_state == UI_STATE_FULL_IDLE) {
            scene_set_clawd_anim(s_scene, CLAWD_ANIM_IDLE);
        }
    }
    _lock_release(&s_lock);
    ESP_LOGI(TAG, "Sleep timeout set to %lu ms", (unsigned long)ms);
}
