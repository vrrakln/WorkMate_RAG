"""Reparse explicitly selected HTML documents into repair artifacts, without touching indexes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from rag.config import Config
from rag.datasources.local_dir import LocalDirectorySource
from rag.ingest.image_parser import configure_images, release_vision
from rag.ingest.readers import read_document


def repair(cfg, files, output):
    if cfg.datasource_type != 'local_dir':
        raise ValueError('补解析仅支持 local_dir')
    root = Path(cfg.datasource_params['root']).resolve()
    selected = {Path(name).resolve() for name in files}
    if not selected or any(not p.is_relative_to(root) or p.suffix.lower() not in ('.htm', '.html') for p in selected):
        raise ValueError('必须明确指定资料目录内的 HTML/HTM 文件')
    output = Path(output).resolve()
    protected = [root, Path(cfg.index_persist_dir).resolve(), Path(cfg.index_q2q_persist_dir).resolve()]
    if any(output.is_relative_to(p) for p in protected):
        raise ValueError('补解析输出必须位于原始资料和现有索引目录之外')
    params = dict(cfg.datasource_params)
    params.pop('include_images', None)
    docs = [d for d in LocalDirectorySource(**params).list_documents() if d.file_path.resolve() in selected]
    if len(docs) != len(selected):
        raise FileNotFoundError('部分指定文件不存在或未被数据源扫描到')
    output.mkdir(parents=True, exist_ok=True)
    configure_images(cfg)
    failures = 0
    try:
        for i, doc in enumerate(docs, 1):
            print(f'[{i}/{len(docs)}] 补解析开始：{doc.file_path}', flush=True)
            try:
                result = read_document(doc)
                record = {'status': 'ok', 'doc_id': doc.doc_id, 'file': str(doc.file_path),
                          'text': result.text, 'metadata': result.metadata,
                          'indexed': False}
                name = hashlib.sha256(str(doc.file_path.resolve()).encode()).hexdigest()+'.json'
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output, delete=False) as f:
                    json.dump(record, f, ensure_ascii=False)
                    temp = f.name
                os.replace(temp, output/name)
                print(f'[{i}/{len(docs)}] 成功，{len(result.text)} 字符，保存于 {output/name}', flush=True)
            except Exception as exc:
                failures += 1
                print(f'[{i}/{len(docs)}] 失败：{type(exc).__name__}: {exc}', flush=True)
    finally:
        release_vision()
    print(f'补解析结束：成功 {len(docs)-failures}/{len(docs)}。仅保存解析结果，尚未合入正文或Q2Q索引。', flush=True)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--file', action='append', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    raise SystemExit(1 if repair(Config.load(args.config), args.file, args.output) else 0)


if __name__ == '__main__':
    main()
