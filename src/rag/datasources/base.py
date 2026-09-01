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
    """知识库中的一个文档（含权限元数据 + 时效元数据）。"""

    doc_id: str
    file_path: Path
    title: str
    doc_type: str                # md | pdf | docx | pptx | ...
    department: str = "unknown"
    confidentiality: str = "public"   # public | internal | secret
    # 时效属性（时间感知 RAG）：同 family_id 的多个版本按 effective_date 取新
    effective_date: str = ""     # 生效日期（ISO，如 2026-01-01）；空 = 无时效约束
    effective_to: str = ""       # 失效日期（ISO）；空 = 未过期
    family_id: str = ""          # 知识族标识（多版本共用）；空 = 单版本
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def metadata(self) -> Dict[str, str]:
        m = {
            "doc_id": self.doc_id,
            "title": self.title,
            "department": self.department,
            "confidentiality": self.confidentiality,
        }
        if self.effective_date:
            m["effective_date"] = self.effective_date
        if self.effective_to:
            m["effective_to"] = self.effective_to
        if self.family_id:
            m["family_id"] = self.family_id
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
