# host/setup.py — py2app configuration for Clawd Tank menubar app
from setuptools import setup

APP = ["clawd_tank_menubar/app.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "AppIcon.icns",
    "plist": {
        "CFBundleName": "Clawd Tank",
        "CFBundleDisplayName": "Clawd Tank",
        "CFBundleIdentifier": "com.clawd-tank.menubar",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,  # menu-bar-only app (no Dock icon)
        "NSBluetoothAlwaysUsageDescription": (
            "Clawd Tank uses Bluetooth to communicate with the ESP32 display."
        ),
    },
    "packages": ["clawd_tank_daemon", "clawd_tank_menubar"],
    "includes": ["rumps", "bleak", "objc"],
    "resources": ["clawd_tank_menubar/icons"],
}

setup(
    name="Clawd Tank",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
