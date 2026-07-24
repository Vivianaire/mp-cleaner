"""文件扩展名 -> 类型映射(仪表盘按类型统计用)。"""
from __future__ import annotations

_TYPE_BY_EXT = {
    "image": {
        "jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "heif",
        "tiff", "tif", "svg", "raw", "cr2", "nef", "arw", "dng",
    },
    "video": {
        "mp4", "mkv", "avi", "mov", "webm", "3gp", "flv", "wmv", "m4v",
        "mpeg", "mpg", "ts", "m2ts",
    },
    "audio": {
        "mp3", "aac", "flac", "ogg", "wav", "m4a", "opus", "wma", "amr",
        "mid", "midi",
    },
    "doc": {
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md",
        "csv", "epub", "rtf", "odt", "ods", "odp",
    },
    "apk": {"apk", "aab", "xapk", "apks", "apkm"},
    "archive": {
        "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "iso",
        "lz", "zst",
    },
}
_EXT2TYPE = {ext: t for t, exts in _TYPE_BY_EXT.items() for ext in exts}

TYPE_ORDER = ["image", "video", "audio", "doc", "apk", "archive", "other"]

# 仪表盘配色(类型 -> 色)
TYPE_COLORS = {
    "image": "#10b981",
    "video": "#3b82f6",
    "audio": "#a855f7",
    "doc": "#64748b",
    "apk": "#f59e0b",
    "archive": "#ef4444",
    "other": "#cbd5e1",
}

TYPE_LABELS = {
    "image": "图片", "video": "视频", "audio": "音频", "doc": "文档",
    "apk": "安装包", "archive": "压缩包", "other": "其他",
}


def file_type(name: str) -> str:
    """按扩展名判类型;无扩展名或未匹配返回 ``other``。"""
    dot = name.rfind(".")
    if dot < 0:
        return "other"
    return _EXT2TYPE.get(name[dot + 1:].lower(), "other")
