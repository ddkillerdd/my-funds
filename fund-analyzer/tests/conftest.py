"""为分析引擎测试提供与工作目录无关的模块路径。"""

import sys
from pathlib import Path


# 将仓库内的 fund-analyzer 根目录加入测试进程的模块搜索路径。
ENGINE_ROOT = Path(__file__).resolve().parents[1]
engine_root_string = str(ENGINE_ROOT)
if engine_root_string not in sys.path:
    sys.path.insert(0, engine_root_string)
