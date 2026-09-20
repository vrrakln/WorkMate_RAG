"""Isolated CPU OCR worker. No model downloads; use bundled or explicit ONNX files."""
import json
import sys
from pathlib import Path


def main():
    from rapidocr_onnxruntime import RapidOCR
    root = Path(sys.argv[1])
    opts = json.loads((root / 'options.json').read_text(encoding='utf-8'))
    kwargs = {key: opts[key] for key in ('det_model_path', 'rec_model_path', 'cls_model_path') if opts.get(key)}
    kwargs.update(intra_op_num_threads=2, inter_op_num_threads=1)
    engine = RapidOCR(**kwargs)
    result, _ = engine(str(root / 'input.png'))
    threshold = float(opts.get('ocr_min_score', 0.5))
    text = '\n'.join(item[1] for item in (result or []) if float(item[2]) >= threshold)
    (root / 'text.txt').write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
