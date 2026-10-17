"""资源路径与物品目录（catalog.json 只读一次）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 打包后资源在 sys._MEIPASS，源码运行时在本文件同级目录。
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))

CATEGORY_ZH = {
    'Building Materials': '建筑材料',
    'Collectibles': '收藏品',
    'Computer Parts': '电脑配件',
    'Electronics': '电子产品',
    'Energy Items': '能源物品',
    'Flammables': '易燃品',
    'Household Items': '家居用品',
    'Instruments': '仪器',
    'Miscellaneous Medical Item': '医疗物品',
    'Miscellaneous Military Item': '军用物品',
    'Paper': '纸制品',
    'Tools': '工具',
}

_catalog: dict = {}


def catalog() -> dict:
    """读取并缓存 catalog.json（sound 分组、物品与参考数据）。"""
    if not _catalog:
        _catalog.update(json.loads((BASE / 'catalog.json').read_text(encoding='utf-8')))
    return _catalog
