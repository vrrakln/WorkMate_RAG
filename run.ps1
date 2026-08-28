# 便捷启动（可移植）：所有路径基于脚本所在目录自动推导，换机器无需改动
# 用法: .\run.ps1 python -m rag.scripts.build_kb
$root = $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $root ".uv-cache"
$env:HF_HUB_DISABLE_XET = "1"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:HF_HOME = Join-Path $root ".data\hf"
uv run @args
