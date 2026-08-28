"""下载 Ollama 安装包（streaming，断点续传）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

URL = "https://ollama.com/download/OllamaSetup.exe"
OUT = Path(__file__).resolve().parent.parent.parent.parent / ".tmp" / "OllamaSetup.exe"


def main() -> None:
    import requests

    OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = OUT.stat().st_size if OUT.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    total = None
    with requests.get(URL, stream=True, timeout=60, headers=headers) as r:
        r.raise_for_status()
        if r.status_code == 206:
            total = existing + int(r.headers.get("content-length", 0))
        else:
            total = int(r.headers.get("content-length", 0))
            existing = 0
            OUT.write_bytes(b"")  # 服务端不支持断点，重头写
        mode = "ab" if existing else "wb"
        done = existing
        with open(OUT, mode) as fh:
            for chunk in r.iter_content(1 << 20):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                pct = done / total * 100 if total else 0
                sys.stdout.write(f"\r{done/1048576:.0f}/{total/1048576:.0f} MB ({pct:.1f}%)")
                sys.stdout.flush()
    print(f"\n下载完成: {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
