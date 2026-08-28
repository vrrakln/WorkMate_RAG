"""公司真实数据源占位实现。

拿到真实知识库后，按实际形态（NAS 目录 / Confluence API / SharePoint / OA 导出）
实现 `KnowledgeSource`，并在 config.yaml 把 datasource.type 指过来。
流水线其余代码（ingest/retrieve/server/eval）不需要任何改动。
"""
from __future__ import annotations

from rag.datasources.base import KbDocument, KnowledgeSource


class CompanyKnowledgeSource(KnowledgeSource):
    name = "company"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def list_documents(self) -> list[KbDocument]:
        raise NotImplementedError(
            "公司知识库数据源尚未实现。请按真实形态实现 list_documents/open_stream：\n"
            "  - 文件目录型: 参考 LocalDirectorySource，扫描挂载盘/同步目录 + manifest\n"
            "  - 知识管理系统: 按导出目录或 REST API 实现\n"
            "完成后在 config.yaml 设置 datasource.type=company。"
        )

    def open_stream(self, doc: KbDocument):  # type: ignore[override]
        raise NotImplementedError("company source not implemented")
