// firmware/main/ui_manager.h
#ifndef UI_MANAGER_H
#define UI_MANAGER_H

#include "lvgl.h"
#include "ble_service.h"

// Initialize UI manager. Must be called after lv_init() and display_init().
void ui_manager_init(void);

// Process a BLE event. Called from the UI task loop.
void ui_manager_handle_event(const ble_evt_t *evt);

// Run one iteration of LVGL timer handler. Called from the UI task loop.
void ui_manager_tick(void);

// Set sleep timeout in milliseconds. 0 = never sleep.
// Takes effect immediately (resets idle timer).
void ui_manager_set_sleep_timeout(uint32_t ms);

#endif // UI_MANAGER_H
