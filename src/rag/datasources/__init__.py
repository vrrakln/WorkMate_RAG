"""数据源工厂。"""
from __future__ import annotations

from rag.datasources.base import KbDocument, KnowledgeSource
from rag.datasources.company_stub import CompanyKnowledgeSource
from rag.datasources.local_dir import LocalDirectorySource

_SOURCES = {
    "local_dir": LocalDirectorySource,
    "company": CompanyKnowledgeSource,
}


def create_source(type_: str, **params) -> KnowledgeSource:
    if type_ not in _SOURCES:
        raise ValueError(f"未知数据源类型: {type_}，可用: {sorted(_SOURCES)}")
    return _SOURCES[type_](**params)


__all__ = [
    "KbDocument",
    "KnowledgeSource",
    "LocalDirectorySource",
    "CompanyKnowledgeSource",
    "create_source",
]
