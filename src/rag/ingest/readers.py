"""格式解析：KbDocument -> llama_index Document（带权限元数据）。"""
from __future__ import annotations

from llama_index.core import Document

from rag.datasources.base import KbDocument


def read_document(doc: KbDocument) -> Document:
    """按扩展名路由到对应 Reader，把文本归一为带元数据的 Document。

    解析质量由 Reader 决定（设计方案 §4.2）；扫描件 OCR / 老 .doc 转 .docx
    等高级路径在后续阶段接入（DLQ + 人工补录）。
    """
    ext = doc.doc_type.lower()

    if ext in {"md", "txt"}:
        text = doc.file_path.read_text(encoding="utf-8", errors="replace")

    elif ext == "pdf":
        from llama_index.readers.file import PDFReader

        reader = PDFReader()
        pages = reader.load_data(doc.file_path)
        text = "\n".join(p.text for p in pages)

    elif ext == "docx":
        from llama_index.readers.file import DocxReader

        reader = DocxReader()
        parts = reader.load_data(doc.file_path)
        text = "\n".join(p.text for p in parts)

    elif ext == "pptx":
        from llama_index.readers.file import PptxReader

        reader = PptxReader()
        slides = reader.load_data(doc.file_path)
        text = "\n".join(s.text for s in slides)

    else:
        raise ValueError(f"不支持的文档格式: {ext}（{doc.file_path.name}）")

    if not text.strip():
        raise ValueError(f"文档解析为空: {doc.file_path.name}（进入 DLQ，人工补录）")

    return Document(text=text, doc_id=doc.doc_id, metadata=doc.metadata)
