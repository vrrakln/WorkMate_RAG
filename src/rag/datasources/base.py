"""数据源适配层：RAG 流水线与"知识库在哪"解耦。

本地开发用 `LocalDirectorySource`（自编样例库）；公司真实数据源按本接口实现，
下游的解析/分块/索引/检索/工具代码不需要任何改动。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Dict


@dataclass
class KbDocument:
    """知识库中的一个文档（含权限元数据）。"""

    doc_id: str
    file_path: Path
    title: str
    doc_type: str                # md | pdf | docx | pptx | ...
    department: str = "unknown"
    confidentiality: str = "public"   # public | internal | secret
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def metadata(self) -> Dict[str, str]:
        m = {
            "doc_id": self.doc_id,
            "title": self.title,
            "department": self.department,
            "confidentiality": self.confidentiality,
        }
        m.update(self.extra)
        return m


class KnowledgeSource(ABC):
    """知识库数据源抽象。实现类只负责「枚举文档 + 打开文件流」"""

    name: str = "base"

    @abstractmethod
    def list_documents(self) -> list[KbDocument]:
        """枚举知识库内所有文档（含部门/密级等元数据）。"""

    @abstractmethod
    def open_stream(self, doc: KbDocument) -> BinaryIO:
        """打开文档文件流。"""
