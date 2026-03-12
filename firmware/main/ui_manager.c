// firmware/main/ui_manager.c
#include "ui_manager.h"
#include "notification.h"
#include "esp_log.h"
#include <stdio.h>

static const char *TAG = "ui";

typedef enum {
    UI_STATE_IDLE,
    UI_STATE_NOTIFICATION,
    UI_STATE_LIST,
    UI_STATE_DISCONNECTED,
} ui_state_t;

static ui_state_t s_state = UI_STATE_DISCONNECTED;
static notification_store_t s_store;
static _lock_t s_lock;

// LVGL objects (placeholder UI)
static lv_obj_t *s_screen = NULL;
static lv_obj_t *s_status_label = NULL;
static lv_obj_t *s_list_container = NULL;

static void rebuild_ui(void);

void ui_manager_init(void) {
    notif_store_init(&s_store);
    s_screen = lv_screen_active();

    // Status label (top area — placeholder for Clawd)
    s_status_label = lv_label_create(s_screen);
    lv_obj_align(s_status_label, LV_ALIGN_TOP_LEFT, 4, 4);
    lv_label_set_text(s_status_label, "[Clawd] Disconnected");

    // Notification list area
    s_list_container = lv_obj_create(s_screen);
    lv_obj_set_size(s_list_container, 200, 150);
    lv_obj_align(s_list_container, LV_ALIGN_TOP_RIGHT, -4, 4);
    lv_obj_set_flex_flow(s_list_container, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_gap(s_list_container, 2, 0);

    rebuild_ui();
    ESP_LOGI(TAG, "UI manager initialized");
}

static void rebuild_ui(void) {
    // Update status label
    int count = notif_store_count(&s_store);

    switch (s_state) {
    case UI_STATE_DISCONNECTED:
        lv_label_set_text(s_status_label, "[Clawd] zzz\nDisconnected");
        break;
    case UI_STATE_IDLE:
        lv_label_set_text(s_status_label, "[Clawd] :)\nAll clear!");
        break;
    case UI_STATE_NOTIFICATION:
    case UI_STATE_LIST:
        {
            char buf[64];
            snprintf(buf, sizeof(buf), "[Clawd] !!\n%d waiting", count);
            lv_label_set_text(s_status_label, buf);
        }
        break;
    }

    // Rebuild notification list
    lv_obj_clean(s_list_container);

    if (count == 0) {
        lv_obj_t *empty = lv_label_create(s_list_container);
        lv_label_set_text(empty, "No notifications");
        return;
    }

    for (int i = 0; i < NOTIF_MAX_COUNT; i++) {
        const notification_t *n = notif_store_get(&s_store, i);
        if (!n) continue;

        lv_obj_t *row = lv_label_create(s_list_container);
        char buf[96];
        snprintf(buf, sizeof(buf), "> %s\n  %s", n->project, n->message);
        lv_label_set_text(row, buf);
        lv_label_set_long_mode(row, LV_LABEL_LONG_CLIP);
        lv_obj_set_width(row, 190);
    }
}

static void update_state(void) {
    int count = notif_store_count(&s_store);
    if (s_state == UI_STATE_DISCONNECTED) return;

    if (count == 0) {
        s_state = UI_STATE_IDLE;
    } else {
        s_state = UI_STATE_LIST;
    }
}

void ui_manager_handle_event(const ble_evt_t *evt) {
    _lock_acquire(&s_lock);

    switch (evt->type) {
    case BLE_EVT_CONNECTED:
        ESP_LOGI(TAG, "Connected");
        s_state = UI_STATE_IDLE;
        break;

    case BLE_EVT_DISCONNECTED:
        ESP_LOGI(TAG, "Disconnected");
        s_state = UI_STATE_DISCONNECTED;
        notif_store_clear(&s_store);
        break;

    case BLE_EVT_NOTIF_ADD:
        ESP_LOGI(TAG, "Add: %s (%s)", evt->id, evt->project);
        notif_store_add(&s_store, evt->id, evt->project, evt->message);
        s_state = UI_STATE_NOTIFICATION;
        break;

    case BLE_EVT_NOTIF_DISMISS:
        ESP_LOGI(TAG, "Dismiss: %s", evt->id);
        notif_store_dismiss(&s_store, evt->id);
        update_state();
        break;

    case BLE_EVT_NOTIF_CLEAR:
        ESP_LOGI(TAG, "Clear all");
        notif_store_clear(&s_store);
        update_state();
        break;
    }

    rebuild_ui();
    _lock_release(&s_lock);
}

void ui_manager_tick(void) {
    _lock_acquire(&s_lock);
    lv_timer_handler();
    _lock_release(&s_lock);
}
