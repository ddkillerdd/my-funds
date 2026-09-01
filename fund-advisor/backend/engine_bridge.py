"""fund-analyzer 引擎路径桥接。

应用层与纯分析引擎位于同一仓库的兄弟目录。
这里统一解析仓库根目录，避免把某台服务器的绝对路径写入业务代码。
"""

from __future__ import annotations

import sys
from pathlib import Path


# 解析仓库内 fund-analyzer 的绝对路径并加入 Python 模块搜索路径。
def ensure_engine_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    engine_path = repo_root / "fund-analyzer"
    if not engine_path.is_dir():
        raise RuntimeError(f"找不到 fund-analyzer 引擎目录：{engine_path}")

    engine_path_string = str(engine_path)
    if engine_path_string not in sys.path:
        sys.path.insert(0, engine_path_string)
    return engine_path
