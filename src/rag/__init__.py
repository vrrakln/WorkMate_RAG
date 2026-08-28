"""internal-rag 包。"""
from __future__ import annotations

import sys

# Windows 控制台默认 GBK，统一 UTF-8 输出（避免中文/符号编码异常）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Windows 环境补丁必须先于任何第三方库加载（huggingface_hub/fastembed）
from rag import _winfix  # noqa: F401

__version__ = "0.1.0"
