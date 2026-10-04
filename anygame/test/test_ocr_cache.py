"""OCR answers a repeat of the same pixels from its cache."""
import numpy as np
from anygame.perceive import ocr


def test_the_same_pixels_are_read_once(monkeypatch):
    calls = []

    def engine():
        def run(img):
            calls.append(img.shape)
            return [(None, "HELLO", 0.9)], None
        return run
    monkeypatch.setattr(ocr, "engine", engine)
    ocr._seen.clear()
    a = np.zeros((20, 40, 3), np.uint8)
    b = a.copy()
    b[5, 5] = 255
    assert ocr._text(a) == "HELLO" and ocr._text(a.copy()) == "HELLO" and len(calls) == 1
    ocr._text(b)
    ocr._text(a, 1.0)
    assert len(calls) == 3                           # other pixels, or another scale, are read again
