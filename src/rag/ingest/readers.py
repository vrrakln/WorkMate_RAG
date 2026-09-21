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
    from rag.ingest.image_parser import active_parser, IMAGE_EXTS, read_pdf_images
    parser = active_parser()

    if ext in {"md", "txt"}:
        text = doc.file_path.read_text(encoding="utf-8", errors="replace")

    elif ext in {"html", "htm"}:
        from rag.ingest.html_parser import html_to_markdown, decode_html

        raw = decode_html(doc.file_path.read_bytes())
        handler = None
        if parser:
            from pathlib import Path
            handler = lambda tag: parser.html_image(tag, doc.file_path, Path(parser.options['root']))
        text = html_to_markdown(raw, image_handler=handler)

    elif ext == "pdf":
        from llama_index.readers.file import PDFReader

        if parser:
            text = read_pdf_images(doc.file_path, parser)
        else:
            reader = PDFReader()
            pages = reader.load_data(doc.file_path)
            text = "\n".join(p.text for p in pages)

    elif '.' + ext in IMAGE_EXTS and parser:
        text = parser.parse(doc.file_path)
        if text:
            text = f'[图片来源：{doc.file_path}]\n{text}'

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
