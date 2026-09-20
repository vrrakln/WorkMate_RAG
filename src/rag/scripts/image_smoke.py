"""Artificial PNG/HTML/PDF acceptance test; no company data required."""
import argparse
import tempfile
from pathlib import Path

from rag.config import Config
from rag.datasources.base import KbDocument
from rag.ingest.image_parser import configure_images, release_vision
from rag.ingest.readers import read_document


def main():
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.pdfgen.canvas import Canvas
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', required=True)
    args = ap.parse_args()
    cfg = Config.load(args.config)
    if not cfg.images.get('enabled'):
        raise SystemExit('请在测试配置启用 images.enabled')
    with tempfile.TemporaryDirectory(prefix='rag-image-smoke-') as folder:
        root = Path(folder)
        cfg.images['root'] = str(root)
        image = Image.new('RGB', (1000, 240), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((30, 60), 'Router A port GE0/0/1', fill='black', font=ImageFont.load_default(size=40))
        image.save(root/'sample.png')
        (root/'sample.html').write_text('<h1>Sample diagram</h1><p>Context</p><img src="sample.png" alt="test diagram">', encoding='utf-8')
        pdf = Canvas(str(root/'sample.pdf'))
        pdf.drawImage(str(root/'sample.png'), 20, 400, width=550, height=132)
        pdf.save()
        configure_images(cfg)
        try:
            for suffix in ('png', 'html', 'pdf'):
                doc = KbDocument('smoke-'+suffix, root/('sample.'+suffix), 'Artificial image test', suffix,
                                 department='test', confidentiality='secret')
                result = read_document(doc)
                if 'Router' not in result.text or 'GE0/0/1' not in result.text:
                    raise AssertionError(f'{suffix}: 未识别出关键文本，实际输出：{result.text}')
                assert result.metadata['confidentiality'] == 'secret'
                print(f'PASS {suffix}: OCR text and ACL preserved', flush=True)
            print('图片入库验收通过（未构建索引）', flush=True)
        finally:
            release_vision()


if __name__ == '__main__':
    main()
