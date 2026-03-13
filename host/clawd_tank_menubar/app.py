# host/clawd_tank_menubar/app.py
"""Clawd Tank macOS status bar application."""

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

import rumps

from clawd_tank_daemon.daemon import ClawdDaemon, DaemonObserver
from clawd_tank_daemon.sim_client import SimClient, SIM_DEFAULT_PORT
from . import hooks, launchd
from .preferences import load_preferences, save_preferences
from .slider import create_slider_menu_item

logger = logging.getLogger("clawd-tank.menubar")

SLEEP_TIMEOUT_OPTIONS = [
    ("1 minute", 60),
    ("2 minutes", 120),
    ("5 minutes", 300),
    ("10 minutes", 600),
    ("30 minutes", 1800),
    ("Never", 0),
]


class ClawdTankApp(rumps.App, DaemonObserver):
    def __init__(self):
        super().__init__("Clawd Tank", quit_button=None)

        self._daemon: Optional[ClawdDaemon] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()
        self._transport_status: dict[str, bool] = {}
        self._notification_count = 0
        self._current_config: dict = {}

        # Build menu — per-transport status
        self._ble_status_item = rumps.MenuItem("BLE: Connecting...", callback=None)
        self._ble_status_item.set_callback(None)
        self._sim_status_item = rumps.MenuItem("", callback=None)
        self._sim_status_item.set_callback(None)

        # Brightness slider — rumps MenuItem with custom NSView
        self._brightness_slider = create_slider_menu_item(
            "Brightness", min_val=0, max_val=255, initial=102,
            on_change=self._on_brightness_change,
        )
        self._brightness_item = rumps.MenuItem("Brightness")
        self._brightness_item._menuitem.setView_(self._brightness_slider.view)

        # Sleep timeout submenu
        self._sleep_menu = rumps.MenuItem("Sleep Timeout")
        self._sleep_timeout_value = 300
        for label, seconds in SLEEP_TIMEOUT_OPTIONS:
            item = rumps.MenuItem(label, callback=self._on_sleep_timeout_select)
            item._seconds = seconds
            if seconds == 300:
                item.state = True
            self._sleep_menu.add(item)

        # Simulator toggle
        self._sim_toggle = rumps.MenuItem("Enable Simulator", callback=self._on_toggle_simulator)
        prefs = load_preferences()
        self._sim_toggle.state = prefs.get("sim_enabled", False)

        # Claude Code hooks
        self._hooks_item = rumps.MenuItem(
            "Install Claude Code Hooks",
            callback=self._on_install_hooks,
        )
        self._hooks_item.state = hooks.are_hooks_installed()

        # Launch at login
        self._login_item = rumps.MenuItem(
            "Launch at Login",
            callback=self._on_toggle_login,
        )
        self._login_item.state = launchd.is_enabled()

        # Reconnect
        self._reconnect_item = rumps.MenuItem("Reconnect", callback=self._on_reconnect)

        # Quit
        self._quit_item = rumps.MenuItem("Quit Clawd Tank", callback=self._on_quit)

        # Assemble menu
        self.menu = [
            self._ble_status_item,
            self._sim_status_item,
            None,
            self._brightness_item,
            None,
            self._sleep_menu,
            None,
            self._sim_toggle,
            None,
            self._hooks_item,
            self._login_item,
            None,
            self._reconnect_item,
            None,
            self._quit_item,
        ]

        # Set initial icon and hide text title so only the icon shows in the menu bar
        self.icon = self._icon_path("crab-disconnected")
        self.template = True
        self.title = ""
        self._update_menu_state()

    @property
    def _connected(self) -> bool:
        return any(self._transport_status.values()) if self._transport_status else False

    # --- Lifecycle ---

    def _start_daemon_thread(self):
        """Start the daemon's asyncio event loop in a background thread."""
        self._daemon = ClawdDaemon(observer=self, headless=False)

        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop_ready.set()
            self._loop.run_until_complete(self._daemon.run())

        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        self._loop_ready.wait(timeout=5)

        # Enable sim transport if preference is set
        if self._sim_toggle.state and self._loop:
            self._transport_status["sim"] = False
            client = SimClient(port=SIM_DEFAULT_PORT)
            asyncio.run_coroutine_threadsafe(
                self._daemon.add_transport("sim", client), self._loop
            )

    # --- DaemonObserver callbacks (called from asyncio thread) ---

    def on_connection_change(self, connected: bool, transport: str = "") -> None:
        if transport:
            self._transport_status[transport] = connected
        if connected and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._read_device_config(), self._loop
            )
        self._schedule_menu_update()

    def on_notification_change(self, count: int) -> None:
        self._notification_count = count
        self._schedule_menu_update()

    # --- Config ---

    async def _read_device_config(self):
        """Read config from device and update menu."""
        if self._daemon:
            config = await self._daemon.read_config()
            if config:
                self._current_config = config
                self._schedule_menu_update()

    def _schedule_menu_update(self):
        """Thread-safe menu update via PyObjC main thread dispatch."""
        try:
            from PyObjCTools.AppHelper import callAfter
            callAfter(self._update_menu_state)
        except ImportError:
            self._update_menu_state()

    def _update_menu_state(self):
        """Update all menu items based on current state. Must run on main thread."""
        connected = self._connected

        # Per-transport status
        ble_connected = self._transport_status.get("ble", False)
        self._ble_status_item.title = f"BLE: {'Connected' if ble_connected else 'Connecting...'}"

        if "sim" in self._transport_status:
            sim_connected = self._transport_status.get("sim", False)
            self._sim_status_item.title = f"Simulator: {'Connected' if sim_connected else 'Connecting...'}"
        else:
            self._sim_status_item.title = ""

        if connected:
            if self._notification_count > 0:
                self.icon = self._icon_path("crab-notifications")
            else:
                self.icon = self._icon_path("crab-connected")

            brightness = self._current_config.get("brightness", 102)
            self._brightness_slider.set_value(brightness)
            self._brightness_slider.set_enabled(True)

            timeout = self._current_config.get("sleep_timeout", 300)
            self._sleep_timeout_value = timeout
            for key, item in self._sleep_menu.items():
                item.state = (item._seconds == timeout)

            self._reconnect_item.set_callback(self._on_reconnect)
        else:
            self.icon = self._icon_path("crab-disconnected")
            self._brightness_slider.set_enabled(False)
            self._reconnect_item.set_callback(None)
        self.title = ""

    def _icon_path(self, name: str) -> Optional[str]:
        """Return path to icon file, or None if not found."""
        import importlib.resources
        try:
            icons_dir = importlib.resources.files("clawd_tank_menubar") / "icons"
            path = icons_dir / f"{name}.png"
            if hasattr(path, '__fspath__'):
                return str(path)
        except Exception:
            pass
        return None

    # --- Menu callbacks ---

    def _on_brightness_change(self, value: int):
        """Called from slider on main thread. Send config write via asyncio."""
        if self._loop and self._connected:
            payload = json.dumps({"brightness": value})
            asyncio.run_coroutine_threadsafe(
                self._daemon.write_config(payload), self._loop
            )

    def _on_sleep_timeout_select(self, sender):
        seconds = sender._seconds
        self._sleep_timeout_value = seconds

        for key, item in self._sleep_menu.items():
            item.state = (item._seconds == seconds)

        if self._loop and self._connected:
            payload = json.dumps({"sleep_timeout": seconds})
            asyncio.run_coroutine_threadsafe(
                self._daemon.write_config(payload), self._loop
            )

    def _on_install_hooks(self, sender):
        if hooks.are_hooks_installed():
            rumps.alert(
                title="Hooks Already Installed",
                message="Claude Code hooks are already configured. "
                        "Restart your Claude Code sessions to pick up any changes.",
            )
            return
        hooks.install_hooks()
        sender.state = True
        rumps.alert(
            title="Hooks Installed",
            message="Claude Code hooks have been added to ~/.claude/settings.json. "
                    "Restart your Claude Code sessions for the hooks to take effect.",
        )

    def _on_toggle_login(self, sender):
        if launchd.is_enabled():
            launchd.disable()
        else:
            launchd.enable()
        sender.state = launchd.is_enabled()

    def _on_toggle_simulator(self, sender):
        """Toggle the simulator transport on/off."""
        sender.state = not sender.state
        save_preferences(prefs={"sim_enabled": sender.state})

        if sender.state:
            self._transport_status["sim"] = False
            self._schedule_menu_update()
            if self._loop and self._daemon:
                client = SimClient(port=SIM_DEFAULT_PORT)
                asyncio.run_coroutine_threadsafe(
                    self._daemon.add_transport("sim", client), self._loop
                )
        else:
            self._transport_status.pop("sim", None)
            self._schedule_menu_update()
            if self._loop and self._daemon:
                asyncio.run_coroutine_threadsafe(
                    self._daemon.remove_transport("sim"), self._loop
                )

    def _on_reconnect(self, _):
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._daemon.reconnect(), self._loop
            )

    def _on_quit(self, _):
        try:
            if self._loop and self._daemon:
                future = asyncio.run_coroutine_threadsafe(
                    self._daemon._shutdown(), self._loop
                )
                future.result(timeout=5)
            rumps.quit_application()
        except Exception:
            logger.exception("Error during quit, force-killing")
            os._exit(1)


def main():
    log_dir = Path.home() / "Library" / "Logs" / "ClawdTank"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "clawd-tank.log"),
        ],
    )
    hooks.install_notify_script()
    app = ClawdTankApp()
    app._start_daemon_thread()
    app.run()


if __name__ == "__main__":
    main()
