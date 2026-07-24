"""清理引擎:前台/运行中应用保护 + 安全删除。"""
from .lockdetect import app_pkg_for_path, mark_protected, protected_packages

__all__ = ["app_pkg_for_path", "mark_protected", "protected_packages"]
