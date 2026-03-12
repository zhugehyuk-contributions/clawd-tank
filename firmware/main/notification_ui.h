#ifndef NOTIFICATION_UI_H
#define NOTIFICATION_UI_H

#include "lvgl.h"
#include "notification.h"

typedef struct notification_ui_t notification_ui_t;

notification_ui_t *notification_ui_create(lv_obj_t *parent);
void notification_ui_show(notification_ui_t *ui, bool show, int anim_ms);
void notification_ui_set_x(notification_ui_t *ui, int x_px);
void notification_ui_rebuild(notification_ui_t *ui, const notification_store_t *store);

/* Call after adding a new notification to show it in expanded hero view,
 * then auto-collapse to compact list after EXPAND_HOLD_MS. */
void notification_ui_trigger_hero(notification_ui_t *ui);

#endif // NOTIFICATION_UI_H
