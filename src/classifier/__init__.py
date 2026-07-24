"""垃圾分类引擎。"""
from .rules import CATEGORY_ORDER, DEFAULT_CHECK, JunkItem, classify

__all__ = ["CATEGORY_ORDER", "DEFAULT_CHECK", "JunkItem", "classify"]
