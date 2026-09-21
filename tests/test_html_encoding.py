import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import json
import os

from rag.ingest.html_parser import decode_html
from rag.ingest.image_parser import image_dependency_signature, ImageParser
from rag.ingest.readers import read_document
from rag.datasources.base import KbDocument
from rag.config import Config
from rag.scripts.repair_html import repair


class EncodingTests(unittest.TestCase):
    def test_repair_only_selected_document_and_preserves_index(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base/'data'
            root.mkdir()
            selected = root/'selected.htm'
            selected.write_bytes('<meta charset="gb2312"><p>保护技术</p>'.encode('gb18030'))
            (root/'other.htm').write_bytes(b'other')
            (root/'manifest.csv').write_text('path,doc_id,confidentiality\nselected.htm,selected-id,secret\n', encoding='utf-8')
            index = base/'index'
            index.mkdir()
            (index/'sentinel').write_bytes(b'original index')
            cfg = Config(project_dir=base, raw={}, datasource_params={'root': str(root)},
                         index_persist_dir=str(index), index_q2q_persist_dir=str(base/'q2q'))
            output = base/'repair'
            with patch('rag.scripts.repair_html.configure_images'), patch('rag.scripts.repair_html.release_vision'), patch.dict(os.environ, {'RAG_IMAGE_OPTIONS': '{}'}):
                self.assertEqual(repair(cfg, [selected], output), 0)
            results = list(output.glob('*.json'))
            self.assertEqual(len(results), 1)
            result = json.loads(results[0].read_text(encoding='utf-8'))
            self.assertEqual(result['doc_id'], 'selected-id')
            self.assertEqual(result['metadata']['confidentiality'], 'secret')
            self.assertFalse(result['indexed'])
            self.assertIn('保护技术', result['text'])
            self.assertEqual((index/'sentinel').read_bytes(), b'original index')
            self.assertEqual(len(list(index.iterdir())), 1)
            with self.assertRaises(ValueError):
                repair(cfg, [selected], index/'repair')

    def test_gb2312_declaration_preserves_chinese_path(self):
        html = '<meta charset="gb2312"><p>保护技术</p><img src="保护技术.files/0.png">'
        self.assertEqual(decode_html(html.encode('gb18030')), html)

    def test_utf8_wins_over_stale_legacy_declaration(self):
        html = '<meta charset="gb2312"><p>保护技术</p>'
        self.assertEqual(decode_html(html.encode('utf-8')), html)

    def test_utf16_bom(self):
        html = '<p>保护技术</p>'
        self.assertEqual(decode_html(html.encode('utf-16')), html)

    def test_invalid_declared_utf8_does_not_silently_replace(self):
        with self.assertRaises(UnicodeError):
            decode_html(b'<meta charset="utf-8">\xff')

    def test_reader_and_dependency_hash_use_same_decoding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root/'保护技术.files/0.png'
            image.parent.mkdir()
            image.write_bytes(b'first')
            page = root/'保护技术.htm'
            page.write_bytes('<meta charset="gb2312"><p>保护技术</p><img src="保护技术.files/0.png">'.encode('gb18030'))
            opts = {'enabled': True, 'root': str(root), 'cache_dir': str(root/'cache')}
            with patch.dict(os.environ, {'RAG_IMAGE_OPTIONS': json.dumps(opts)}):
                before = image_dependency_signature(page, 'htm')
                image.write_bytes(b'second')
                self.assertNotEqual(before, image_dependency_signature(page, 'htm'))
                with patch.object(ImageParser, 'parse', return_value='image text') as parse:
                    doc = read_document(KbDocument('one', page, '保护技术', 'htm', confidentiality='secret'))
                    parse.assert_called_once_with(image)
                    self.assertIn('保护技术', doc.text)
                    self.assertNotIn('\ufffd', doc.text)
                    self.assertEqual(doc.metadata['confidentiality'], 'secret')


if __name__ == '__main__':
    unittest.main()
