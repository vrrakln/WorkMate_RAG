import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from rag.ingest.image_parser import ImageParser, resolve_image, configure_images
from rag.ingest.html_parser import html_to_markdown
from rag.datasources.local_dir import LocalDirectorySource
from rag.config import Config
from rag.ingest.image_parser import image_dependency_signature, read_pdf_images


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.png = self.root / 'diagram.png'
        Image.new('RGB', (200, 120), 'white').save(self.png)
        self.options = {'enabled': True, 'cache_dir': str(self.root/'cache'),
                        'min_side': 1, 'vision_enabled': False}

    def test_local_resolution_and_external_rejection(self):
        page = self.root/'page.html'
        self.assertEqual(resolve_image('diagram.png?v=1', page, self.root), self.png)
        for src in ['https://example.com/x.png', '//example.com/x', '../secret.png', 'data:image/png;base64,x']:
            with self.assertRaises(ValueError):
                resolve_image(src, page, self.root)

    def test_success_cache_and_content_invalidation(self):
        parser = ImageParser(self.options)
        with patch.object(parser, '_ocr', return_value='router A') as ocr:
            self.assertIn('router A', parser.parse(self.png))
            self.assertIn('router A', parser.parse(self.png))
            self.assertEqual(ocr.call_count, 1)
            Image.new('RGB', (200, 120), 'black').save(self.png)
            parser.parse(self.png)
            self.assertEqual(ocr.call_count, 2)

    def test_failure_retries_without_poisoning_success_cache(self):
        parser = ImageParser(self.options)
        with patch.object(parser, '_ocr', side_effect=TimeoutError('slow')):
            with self.assertRaises(TimeoutError):
                parser.parse(self.png)
        with patch.object(parser, '_ocr', return_value='retried'):
            self.assertIn('retried', parser.parse(self.png))

    def test_nested_html_images_keep_context(self):
        html = '<h1>Network</h1><table><tr><td><img src="diagram.png"></td></tr></table><p>end</p>'
        result = html_to_markdown(html, image_handler=lambda tag: 'image evidence')
        self.assertIn('Network', result)
        self.assertIn('image evidence', result)
        self.assertIn('end', result)

    def test_image_scan_opt_in_unique_ids_and_manifest_acl(self):
        (self.root/'sub').mkdir()
        Image.new('RGB', (100, 100)).save(self.root/'sub/diagram.png')
        self.assertEqual(LocalDirectorySource(self.root).list_documents(), [])
        (self.root/'manifest.csv').write_text('path,department,confidentiality\ndiagram.png,ops,secret\n', encoding='utf-8')
        docs = LocalDirectorySource(self.root, include_images=True).list_documents()
        self.assertEqual(len(docs), 2)
        self.assertEqual(len({d.doc_id for d in docs}), 2)
        doc = next(d for d in docs if d.file_path == self.png)
        self.assertEqual(doc.confidentiality, 'secret')
        self.assertTrue(all(d.confidentiality == 'secret' for d in docs))

    def test_disabled_config_clears_worker_environment(self):
        cfg = Config(project_dir=self.root, raw={})
        with patch.dict(os.environ, {'RAG_IMAGE_OPTIONS': '{"enabled":true}'}):
            configure_images(cfg)
            self.assertNotIn('RAG_IMAGE_OPTIONS', os.environ)

    def test_html_dependency_cache_detects_image_change(self):
        import json
        page = self.root/'page.html'
        page.write_text('<img src="diagram.png">', encoding='utf-8')
        options = dict(self.options, root=str(self.root))
        with patch.dict(os.environ, {'RAG_IMAGE_OPTIONS': json.dumps(options)}):
            before = image_dependency_signature(page, 'html')
            Image.new('RGB', (200, 120), 'blue').save(self.png)
            self.assertNotEqual(before, image_dependency_signature(page, 'html'))

    def test_pdf_mixed_page_preserves_text_and_image_evidence(self):
        from reportlab.pdfgen.canvas import Canvas
        path = self.root/'mixed.pdf'
        canvas = Canvas(str(path))
        canvas.drawString(30, 700, 'Original text and diagram')
        canvas.drawImage(str(self.png), 30, 500, width=200, height=120)
        canvas.save()
        parser = ImageParser(self.options)
        with patch.object(parser, 'parse_bytes', return_value='image evidence') as parse:
            text = read_pdf_images(path, parser)
            self.assertIn('Original text', text)
            self.assertIn('image evidence', text)
            self.assertIn('第 1 页', text)
            self.assertEqual(parse.call_count, 1)

    def test_missing_embedded_image_fails_instead_of_caching_omission(self):
        from bs4 import BeautifulSoup
        parser = ImageParser(self.options)
        tag = BeautifulSoup('<img src="missing.png">', 'lxml').img
        with self.assertRaises(FileNotFoundError):
            parser.html_image(tag, self.root/'page.html', self.root)

    def test_vision_failure_has_no_success_marker(self):
        parser = ImageParser(dict(self.options, vision_enabled=True))
        with patch.object(parser, '_ocr', return_value='OCR'), patch('rag.ingest.image_parser.api_json', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                parser.parse(self.png)
        self.assertEqual(list(parser.cache.glob('*.json')), [])

    def test_real_reader_reuses_text_with_current_acl(self):
        import json
        from rag.datasources.base import KbDocument
        from rag.ingest.readers import read_document
        with patch.dict(os.environ, {'RAG_IMAGE_OPTIONS': json.dumps(self.options)}):
            with patch.object(ImageParser, '_ocr', return_value='test text'):
                first = read_document(KbDocument('a', self.png, 'title', 'png', confidentiality='secret'))
            with patch.object(ImageParser, '_ocr', side_effect=AssertionError('must use cache')):
                second = read_document(KbDocument('b', self.png, 'title', 'png', confidentiality='internal'))
        self.assertEqual(first.metadata['confidentiality'], 'secret')
        self.assertEqual(second.metadata['confidentiality'], 'internal')
        self.assertEqual(second.metadata['file_path'], str(self.png))

    def test_ocr_process_has_enforced_timeout(self):
        import subprocess
        parser = ImageParser(self.options)
        with patch('rag.ingest.image_parser.subprocess.run', side_effect=subprocess.TimeoutExpired('ocr', 180)):
            with self.assertRaises(subprocess.TimeoutExpired):
                parser.parse(self.png)

    def test_disabled_html_keeps_legacy_alt(self):
        text = html_to_markdown('<p>Before</p><img src="missing.png" alt="diagram"><p>After</p>')
        self.assertIn('[图片：diagram]', text)
        self.assertIn('Before', text)

    def test_image_text_reaches_persisted_index_with_acl(self):
        import json
        from llama_index.core.embeddings import MockEmbedding
        from rag.ingest.pipeline import build_kb
        data = self.root/'data'
        data.mkdir()
        Image.new('RGB', (200, 120), 'white').save(data/'router.png')
        cfg = Config(project_dir=self.root, raw={},
                     datasource_params={'root': str(data)},
                     index_persist_dir=str(self.root/'index'),
                     index_q2q_persist_dir=str(self.root/'q2q'),
                     images={'enabled': True, 'include_standalone': True,
                             'cache_dir': str(self.root/'images-cache')})
        with patch.dict(os.environ, {}, clear=False):
            with patch('rag.ingest.pipeline.build_embed_model', return_value=MockEmbedding(embed_dim=8)), patch.object(ImageParser, '_ocr', return_value='Router A uses port GE0/0/1'):
                build_kb(cfg)
        lines = (self.root/'index/nodes.jsonl').read_text(encoding='utf-8').splitlines()
        node = json.loads(lines[0])
        self.assertIn('GE0/0/1', node['text'])
        self.assertEqual(node['metadata']['confidentiality'], 'secret')
        self.assertEqual(node['metadata']['file_path'], str(data/'router.png'))

    def test_config_datasource_relative_path_is_not_prefixed_twice(self):
        import json
        config_dir = self.root/'config'
        config_dir.mkdir()
        config = config_dir/'sample.yaml'
        config.write_text('datasource:\n  params:\n    root: ../data\nimages:\n  enabled: true\n  cache_dir: ../cache\n', encoding='utf-8')
        with patch.dict(os.environ, {}, clear=False):
            configure_images(Config.load(config))
            opts = json.loads(os.environ['RAG_IMAGE_OPTIONS'])
            self.assertEqual(Path(opts['root']), self.root/'data')

    def test_htm_scanned_without_enabling_standalone_images(self):
        (self.root/'page.htm').write_text('<p>test</p>', encoding='utf-8')
        docs = LocalDirectorySource(self.root).list_documents()
        self.assertEqual([d.doc_type for d in docs], ['htm'])


if __name__ == '__main__':
    unittest.main()
