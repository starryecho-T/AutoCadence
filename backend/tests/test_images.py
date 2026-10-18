import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from vai_backend.images import ImageError, _canvas_stats, _decode_xwd, convert_and_validate


# Positive fixtures: the verified real M1 backend run (result.json, image_validation.json
# and the user-reviewed screenshots all reference this evidence). runs/ is local-only;
# tests skip when it is not present in the portable source package.
VERIFIED = Path(__file__).resolve().parents[1] / 'runs' / 'vai_20261018_141418_21e24c15' / 'evidence'
# Negative fixture: the historical blank-canvas XWD captured before the redraw fix.
BLANK_XWD = Path(__file__).resolve().parents[3] / 'work' / 'm1' / 'gui' / 'schematic_window_0.xwd'


class ImageEvidenceTests(unittest.TestCase):
    def setUp(self):
        if not VERIFIED.is_dir():
            self.skipTest('Verified real-run evidence is not included in the portable source package')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for kind in ('schematic', 'waveform'):
            shutil.copyfile(VERIFIED / f'{kind}_window.xwd',
                            self.root / f'{kind}_window.xwd')
            shutil.copyfile(VERIFIED / f'{kind}_native.png',
                            self.root / f'{kind}_native.png')

    def test_verified_cadence_evidence_passes_and_pixels_are_unchanged(self):
        result = convert_and_validate(self.root)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['images']), 4)
        for kind in ('schematic', 'waveform'):
            actual = Image.open(self.root / f'{kind}_window.png').convert('RGB')
            original = Image.open(VERIFIED / f'{kind}_window.png').convert('RGB')
            self.assertIsNone(ImageChops.difference(actual, original).getbbox())

    def test_real_blank_schematic_xwd_is_rejected_despite_visible_toolbar(self):
        if not BLANK_XWD.is_file():
            self.skipTest('Historical blank-canvas XWD fixture is not bundled')
        shutil.copyfile(BLANK_XWD, self.root / 'schematic_window.xwd')
        with self.assertRaisesRegex(ImageError, 'schematic window canvas is empty'):
            convert_and_validate(self.root)

    def test_waveform_toolbar_and_legend_do_not_replace_traces(self):
        image = Image.open(VERIFIED / 'waveform_window.png').convert('RGB')
        ImageDraw.Draw(image).rectangle((475, 180, 975, 702), fill='black')
        with self.assertRaisesRegex(ImageError, 'waveform window canvas is empty'):
            _canvas_stats(image, 'waveform')

    def test_truncated_xwd_is_rejected(self):
        path = self.root / 'schematic_window.xwd'
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(ImageError, 'truncated or trailing'):
            convert_and_validate(self.root)

    def test_wrong_pixel_masks_are_rejected(self):
        path = self.root / 'schematic_window.xwd'
        data = path.read_bytes()
        h = list(struct.unpack('>25I', data[:100]))
        h[14] = 255
        path.write_bytes(struct.pack('>25I', *h) + data[100:])
        with self.assertRaisesRegex(ImageError, 'unsupported XWD format'):
            _decode_xwd(path)

    def test_corrupt_native_png_is_rejected(self):
        (self.root / 'schematic_native.png').write_bytes(b'not a PNG')
        with self.assertRaisesRegex(ImageError, 'native image cannot be decoded'):
            convert_and_validate(self.root)

    def test_blank_native_png_is_rejected(self):
        Image.new('RGB', (1500, 453), 'black').save(self.root / 'schematic_native.png')
        with self.assertRaisesRegex(ImageError, 'schematic native canvas is empty'):
            convert_and_validate(self.root)


if __name__ == '__main__':
    unittest.main()
