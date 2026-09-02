"""本地目录型数据源：扫描目录 + 读取 manifest.csv 元数据。"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import BinaryIO

from rag.datasources.base import KbDocument, KnowledgeSource

_SUPPORTED_EXTS = {".md", ".pdf", ".docx", ".pptx", ".txt", ".html"}


class LocalDirectorySource(KnowledgeSource):
    """从本地目录加载文档。

    manifest.csv（可选，UTF-8 with BOM）列：
        path, doc_id, title, department, confidentiality, doc_type
    path 为相对根目录的路径；缺省列取默认值。
    """

    name = "local_dir"

    def __init__(self, root: str | Path, manifest: str | Path | None = None):
        self.root = Path(root)
        self.manifest = Path(manifest) if manifest else self.root / "manifest.csv"

    def list_documents(self) -> list[KbDocument]:
        meta = self._read_manifest()  # path -> row
        docs: list[KbDocument] = []
        for f in sorted(self.root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in _SUPPORTED_EXTS:
                continue
            rel = f.relative_to(self.root).as_posix()
            row = meta.get(rel) or {}
            docs.append(
                KbDocument(
                    doc_id=row.get("doc_id") or f.stem,
                    file_path=f,
                    title=row.get("title") or f.stem,
                    doc_type=(row.get("doc_type") or f.suffix.lower().lstrip(".")),
                    department=row.get("department", "unknown"),
                    confidentiality=row.get("confidentiality", "public"),
                    effective_date=row.get("effective_date", ""),
                    effective_to=row.get("effective_to", ""),
                    family_id=row.get("family_id", ""),
                    extra={
                        k: v
                        for k, v in row.items()
                        if k not in {
                            "path", "doc_id", "title", "department", "confidentiality", "doc_type",
                            "effective_date", "effective_to", "family_id",
                        }
                    },
                )
            )
        return docs

    def open_stream(self, doc: KbDocument) -> BinaryIO:
        return open(doc.file_path, "rb")

    def _read_manifest(self) -> dict[str, dict[str, str]]:
        if not self.manifest.exists():
            return {}
        rows: dict[str, dict[str, str]] = {}
        with open(self.manifest, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                key = r.get("path") or r.get("filename")
                if key:
                    rows[key] = r
        return rows
