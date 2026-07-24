"""垃圾文件分类规则(据报告「垃圾文件智能分类与风险评估模型」表)。

类别与风险:
- 缓存 / 缩略图 / 已卸载残留 / 日志 / 废弃文件        -> 安全(默认勾选)
- 空文件夹                                            -> 中等(量大且不释放空间,手动勾选清理)
- 大文件 / 重复文件                                        -> 中等(仅列出,不自动勾选)
- 系统应用(com.android.* 等)私有目录下的缓存/废弃项      -> 降为「中等」(保守,不默认删)

规则要点:
- 目录类目(缓存/缩略图/残留)整体覆盖其子树:命中后不再细分子项,避免重复。
- 一个节点只进一个类别(yielded 集合)。
- 「空文件夹」=无子项的目录;「废弃文件夹」=直接子项全是废弃/日志文件的目录(连同内容整体清理)。
- 大文件用 mtime 判定陈旧(Android 多 noatime,atime 不可靠)。
- 重复文件先「按大小预筛」出候选;候选再由后台 ``DedupWorker`` 采样哈希复核。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..scanner.trie import FileTrie, Node

LARGE_FILE_BYTES = 100 * 1024 * 1024          # 100 MB
STALE_SECS = 180 * 24 * 3600                  # 半年
DUP_MIN_BYTES = 5 * 1024 * 1024               # 重复候选最小体积

CATEGORY_ORDER = [
    "缓存", "缩略图", "已卸载残留", "日志", "废弃文件", "空文件夹", "大文件", "重复文件",
]
RISK = {
    "缓存": "安全",
    "缩略图": "安全",
    "已卸载残留": "安全",
    "日志": "安全",
    "废弃文件": "安全",
    "空文件夹": "中等",
    "大文件": "中等",
    "重复文件": "中等",
}
DEFAULT_CHECK = {
    "缓存": True,
    "缩略图": True,
    "已卸载残留": True,
    "日志": True,
    "废弃文件": True,
    "空文件夹": False,
    "大文件": False,
    "重复文件": False,
}

# 目录名(小写)精确匹配
_CACHE_NAMES = {"cache", "__cache__", "caches", ".cache", "temp", "tmp", "tempcache"}
_THUMB_NAMES = {".thumbnails", ".thumbdata", ".thumbs", "thumbnails"}

# 文件后缀(小写,endswith tuple 判定)
_LOG_EXTS = (".log", ".err", ".crash", ".dump", ".tombstone", ".anr")           # 日志 + 崩溃转储
_WASTE_EXTS = (".tmp", ".temp", ".bak", ".old", ".orig", ".swp", ".part",
               ".crdownload", ".apk", ".apks", ".apkm")                          # 临时/备份/下载残留/旧安装包


@dataclass
class JunkItem:
    category: str
    risk: str
    node: Node
    size: int
    path: str
    protected: bool = False


def _is_residue(node: Node, installed: set[str]) -> bool:
    """Android/data|obb/<pkg> 且 <pkg> 未安装。"""
    p = node.parent
    if p is None or p.name not in ("data", "obb"):
        return False
    pp = p.parent
    if pp is None or pp.name != "Android":
        return False
    return node.name not in installed


def _categorize(node: Node, installed: set[str]) -> str | None:
    """返回该节点命中的类别(目录类目 / 日志 / 废弃文件),否则 None。"""
    if not node.is_file:
        lname = node.name.lower()
        # installed 为空 = pm 查询失败,而非真的没装应用(真机必有数百个)。
        # 此时**跳过残留判定**,否则会把所有 Android/data/* 误标为「已卸载残留」
        # (安全类,默认勾选、可一键删),酿成误删活数据。
        if installed and _is_residue(node, installed):
            return "已卸载残留"
        if lname in _THUMB_NAMES:
            return "缩略图"
        if lname in _CACHE_NAMES:
            return "缓存"
        return None
    # 文件:日志 / 废弃文件(大文件/重复走另一支,避免与目录逻辑混淆)
    lname = node.name.lower()
    if lname.endswith(_LOG_EXTS) or "error_log" in lname:
        return "日志"
    if lname.endswith(_WASTE_EXTS) or lname.endswith("~"):
        return "废弃文件"
    return None


def classify(
    trie: FileTrie, installed_pkgs, third_party_pkgs, now_ts: float
) -> list[JunkItem]:
    """遍历 trie,产出按类别归组的垃圾项。

    third_party_pkgs 用于系统保守:installed − third_party = 系统应用,其私有目录下的
    缓存/废弃项降为「中等」(不默认勾选),避免误删系统应用数据。第三方应用保持「安全」。
    """
    from ..cleaner.lockdetect import app_pkg_for_path   # 局部导入,避开模块级循环引用

    installed = set(installed_pkgs)
    system_pkgs = installed - set(third_party_pkgs or []) if third_party_pkgs else set()
    items: list[JunkItem] = []
    dup_by_size: dict[int, list[Node]] = {}
    yielded: set[int] = set()

    def emit(cat: str, node: Node, size: int) -> None:
        if id(node) in yielded:
            return
        yielded.add(id(node))
        risk = RISK[cat]
        # 系统应用保守:app 私有目录下的缓存/废弃项降级为「中等」
        if risk == "安全" and system_pkgs and cat in ("缓存", "废弃文件"):
            pkg = app_pkg_for_path(node.abs_path())
            if pkg and pkg in system_pkgs:
                risk = "中等"
        items.append(
            JunkItem(
                category=cat,
                risk=risk,
                node=node,
                size=size,
                path=node.abs_path(),
            )
        )

    def walk(node: Node) -> None:
        cat = _categorize(node, installed)
        if cat is not None:
            emit(cat, node, node.total if not node.is_file else node.own_size)
            return  # 目录:子树整体覆盖;文件:无子树
        if node.is_file:
            sz = node.own_size
            if sz >= LARGE_FILE_BYTES and (now_ts - node.mtime) >= STALE_SECS:
                emit("大文件", node, sz)
            if sz >= DUP_MIN_BYTES:
                dup_by_size.setdefault(sz, []).append(node)
            return
        # 目录,未命中 cache/thumb/residue
        kids = node.children or {}
        if not kids:
            emit("空文件夹", node, 0)                  # 纯空目录
            return
        if all(k.is_file and _categorize(k, installed) in ("日志", "废弃文件") for k in kids.values()):
            emit("废弃文件", node, node.total)          # 直接子项全废弃 → 整个目录(eh 例子)
            return
        for child in kids.values():
            walk(child)

    for child in (trie.root.children or {}).values():
        walk(child)

    # 重复文件(按大小预筛)
    for nodes in dup_by_size.values():
        if len(nodes) > 1:
            for n in nodes:
                emit("重复文件", n, n.own_size)

    return items
