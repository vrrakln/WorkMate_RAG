# 便捷启动：设置工作区内 uv 缓存 + HF Hub 适配，再转发到 uv run
# 用法: .\run.ps1 python -m rag.scripts.generate_sample
$env:UV_CACHE_DIR = "C:\Users\zyw_tx2\Desktop\RAG-build\rag\.uv-cache"
$env:HF_HUB_DISABLE_XET = "1"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:HF_HOME = "C:\Users\zyw_tx2\Desktop\RAG-build\rag\.data\hf"
uv run @args
