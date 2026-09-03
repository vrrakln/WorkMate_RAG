"""Windows 环境补丁：tempfile.mkdtemp 用默认权限创建目录。

背景：本机（以及部分 Windows 环境）对「以 POSIX mode=0o700 创建的目录」会附加
收紧的 ACL，之后任何进程都无法再向其中写入文件（PermissionError 13），且
os.chmod 无法修复（Windows chmod 不改变 ACL）。huggingface_hub 的下载事务
依赖 tempfile.mkdtemp（内部 os.mkdir(mode=0o700)）→ 模型下载必然失败。

本补丁让 mkdtemp 用默认权限（0777）创建目录，huggingface_hub 下载即可正常
落地；链接创建（symlink 无特权时）hf_hub 会降级为复制文件，同样可用。
"""
from __future__ import annotations

import os
import random
import string
import tempfile
from pathlib import Path


def _mkdtemp_default_mode(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
    """mkdtemp 的等价实现，但目录用默认权限创建（不带 mode=0o700）。"""
    prefix = prefix or "tmp"
    suffix = suffix or ""
    base = os.path.abspath(dir) if dir else tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)
    chars = string.ascii_letters + string.digits
    for _ in range(200):
        name = os.path.join(base, f"{prefix}{''.join(random.choices(chars, k=8))}{suffix}")
        try:
            os.mkdir(name)  # 默认权限
            return name
        except FileExistsError:
            continue
    raise FileExistsError(f"无法创建临时目录: {base}")


def _apply() -> None:
    if getattr(_apply, "_done", False):
        return
    tempfile.mkdtemp = _mkdtemp_default_mode  # type: ignore[assignment]

    # llama-index 的 NLTK 等缓存默认写 %LOCALAPPDATA%\llama_index（工作区外，
    # 沙箱会拒）——重定向到项目内 .data/llama_cache
    try:
        import platformdirs

        _project = Path(__file__).resolve().parent.parent.parent
        _llama_cache = str(_project / ".data" / "llama_cache")

        def _user_cache_dir(name, *a, **k):
            if name == "llama_index":
                return _llama_cache
            return _orig_user_cache_dir(name, *a, **k)

        _orig_user_cache_dir = platformdirs.user_cache_dir
        platformdirs.user_cache_dir = _user_cache_dir  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 - 补丁失败不阻塞主流程
        pass
    _apply._done = True  # type: ignore[attr-defined]


_apply()
