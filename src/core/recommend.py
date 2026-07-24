"""自动分析:建议引擎。

扫描后产出排序建议表 ``(key, title, detail, reclaimable, safety, items, auto)``。
排序按可回收量降序;``auto=True`` 的建议纳入「一键优化」。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Recommendation:
    key: str
    title: str
    detail: str
    reclaimable: int
    safety: str            # "安全" | "中等"
    items: list = field(default_factory=list)
    auto: bool = False     # 是否被「一键优化」纳入(自动执行)


def generate(junk_items) -> list[Recommendation]:
    recs: list[Recommendation] = []
    safe = [it for it in junk_items if it.risk == "安全"]
    if safe:
        cats = sorted({it.category for it in safe})
        recs.append(
            Recommendation(
                "clean_safe", "清理安全垃圾",
                f"{' / '.join(cats)},共 {len(safe)} 项",
                sum(i.size for i in safe), "安全", safe, auto=True,
            )
        )
    large = [it for it in junk_items if it.category == "大文件"]
    if large:
        recs.append(
            Recommendation(
                "review_large", "审视大文件",
                f"{len(large)} 个 >100MB 且超半年未动(需你判断保留/清理)",
                sum(i.size for i in large), "中等", large, auto=False,
            )
        )
    dup = [it for it in junk_items if it.category == "重复文件"]
    if dup:
        # 重复去重保守估计:每组保留一份,可回收约一半
        recs.append(
            Recommendation(
                "review_dup", "审视重复文件",
                f"{len(dup)} 个疑似重复(已采样哈希复核,需人工确认)",
                sum(i.size for i in dup) // 2, "中等", dup, auto=False,
            )
        )
    recs.sort(key=lambda r: -r.reclaimable)
    return recs


def one_tap_items(recs: list[Recommendation]) -> list:
    """「一键优化」收集所有 auto 建议的目标项。"""
    seen: set[int] = set()
    out = []
    for r in recs:
        if not r.auto:
            continue
        for it in r.items:
            if id(it) not in seen:
                seen.add(id(it))
                out.append(it)
    return out
