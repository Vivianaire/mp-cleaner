"""ADB 封装层。"""
from .client import AdbClient, AdbError, DeviceInfo
from .paths import ANDROID_DATA, SCAN_ROOT, SDCARD, TRASH_DIR, dirs_command, scan_command

__all__ = [
    "AdbClient",
    "AdbError",
    "DeviceInfo",
    "SCAN_ROOT",
    "SDCARD",
    "ANDROID_DATA",
    "TRASH_DIR",
    "scan_command",
    "dirs_command",
]
