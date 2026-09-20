"""本地目录型数据源：扫描目录 + 读取 manifest.csv 元数据。"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import BinaryIO

from rag.datasources.base import KbDocument, KnowledgeSource

_SUPPORTED_EXTS = {".md", ".pdf", ".docx", ".pptx", ".txt", ".html", ".htm"}


class LocalDirectorySource(KnowledgeSource):
    """从本地目录加载文档。

    manifest.csv（可选，UTF-8 with BOM）列：
        path, doc_id, title, department, confidentiality, doc_type
    path 为相对根目录的路径；缺省列取默认值。
    """

    name = "local_dir"

    def __init__(self, root: str | Path, manifest: str | Path | None = None, include_images: bool = False):
        self.root = Path(root)
        self.include_images = include_images
        self.manifest = Path(manifest) if manifest else self.root / "manifest.csv"

    def list_documents(self) -> list[KbDocument]:
        meta = self._read_manifest()  # path -> row
        docs: list[KbDocument] = []
        from rag.ingest.image_parser import IMAGE_EXTS
        supported = _SUPPORTED_EXTS | (IMAGE_EXTS if self.include_images else set())
        for f in sorted(self.root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in supported:
                continue
            rel = f.relative_to(self.root).as_posix()
            row = meta.get(rel) or {}
            docs.append(
                KbDocument(
                    doc_id=row.get("doc_id") or ('image_' + hashlib.sha256(rel.encode()).hexdigest() if f.suffix.lower() in IMAGE_EXTS else f.stem),
                    file_path=f,
                    title=row.get("title") or f.stem,
                    doc_type=(row.get("doc_type") or f.suffix.lower().lstrip(".")),
                    department=row.get("department", "unknown"),
                    confidentiality=row.get("confidentiality") or ('secret' if f.suffix.lower() in IMAGE_EXTS else 'public'),
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
