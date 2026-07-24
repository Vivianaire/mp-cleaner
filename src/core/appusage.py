"""应用占用 & 使用度分析(纯 adb shell,uid 2000)。

数据源:
- ``dumpsys diskstats``:权威 per-app 存储口径,含 ``/data/data/<pkg>`` 私有数据
  (全盘 ``find`` 看不到);
- ``am get-inactive <pkg>``:系统 app-standby 闲置判定(长期未用信号)。

产出「占用大、且系统判为闲置」的应用清单,供仪表盘展示 —— 这是各家清理工具的
核心启发式(体积 × 使用度),本项目此前缺失。仅提示,不代删应用。
"""
from __future__ import annotations

from dataclasses import dataclass

# 只对「体积够大」的应用查询闲置态,给结果与 shell 调用次数都设上限
_IDLE_MIN_TOTAL = 30 * 1024 * 1024        # 查 idle 的最小 per-app 体积
_IDLE_MAX_QUERIES = 30                     # 最多查多少个应用的 idle(限 adb 往返)
_UNUSED_MIN_TOTAL = 100 * 1024 * 1024     # 计入「未用大应用」的最小体积


@dataclass
class AppUsage:
    pkg: str
    total: int          # app + data(字节)
    data: int
    cache: int
    idle: bool | None   # True 闲置 / False 活跃 / None 未知


def analyze(backend, top_n: int = 40) -> list[AppUsage]:
    """按占用排名取前 top_n 第三方应用,对够大者查询闲置态。

    返回按 total 降序的 AppUsage 列表;diskstats 不可用时返回 []。
    """
    stats = backend.disk_stats()
    if not stats:
        return []
    try:
        third = set(backend.third_party_packages())
    except Exception:  # noqa: BLE001
        third = set()

    ranked = sorted(
        (
            (pkg, s)
            for pkg, s in stats.items()
            if not third or pkg in third
        ),
        key=lambda kv: -kv[1].get("total", 0),
    )[:top_n]

    out: list[AppUsage] = []
    queries = 0
    for pkg, s in ranked:
        total = s.get("total", 0)
        idle: bool | None = None
        if total >= _IDLE_MIN_TOTAL and queries < _IDLE_MAX_QUERIES:
            idle = backend.app_idle(pkg)
            queries += 1
        out.append(
            AppUsage(
                pkg=pkg,
                total=total,
                data=s.get("data", 0),
                cache=s.get("cache", 0),
                idle=idle,
            )
        )
    return out


def unused_large(apps: list[AppUsage], min_total: int = _UNUSED_MIN_TOTAL) -> list[AppUsage]:
    """占用 >= 阈值 且被系统判为闲置的应用(建议用户自行卸载/清数据)。"""
    return [a for a in apps if a.idle is True and a.total >= min_total]
