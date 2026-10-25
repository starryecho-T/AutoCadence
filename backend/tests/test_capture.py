import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'worker' / 'capture.py'
SPEC = importlib.util.spec_from_file_location('worker_capture', SOURCE)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class CapturePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'evidence'
        self.out.mkdir()

    def test_rc_captures_transient_and_ac_with_distinct_files(self):
        cell, plots = capture._plot_settings(str(self.root))
        self.assertEqual(cell, 'rc_lpf')
        self.assertEqual([(p['analysis'], p['stage']) for p in plots],
                         [('tran', 'waveform'), ('ac', 'waveform_ac')])
        script = capture._script(str(self.root), 'vai_run123', str(self.out), cell, plots)
        self.assertIn("selectResults('tran)", script)
        self.assertIn("selectResults('ac)", script)
        self.assertIn('procedure(vaiWave0()', script)
        self.assertIn('procedure(vaiWave1()', script)
        self.assertIn('waveform_ac.ready', script)
        self.assertIn('waveform_ac_native', script)
        self.assertIn('db20(v("out"))', script)

    def test_general_skips_op_when_curve_analyses_exist(self):
        config = {'cell': 'general', 'analysis': 'tran', 'expressions': ['v("out")'],
                  'labels': ['out'], 'plots': [
                      {'analysis': 'op', 'expressions': ['v("out")'], 'labels': ['out']},
                      {'analysis': 'ac', 'expressions': ['mag(v("out"))'], 'labels': ['out AC']},
                      {'analysis': 'tran', 'expressions': ['v("out")'], 'labels': ['out']}]}
        (self.root / 'capture_config.json').write_text(json.dumps(config), encoding='utf-8')
        cell, plots = capture._plot_settings(str(self.root))
        self.assertEqual(cell, 'general')
        self.assertEqual([(p['analysis'], p['stage']) for p in plots],
                         [('ac', 'waveform'), ('tran', 'waveform_tran')])
        script = capture._script(str(self.root), 'vai_run123', str(self.out), cell, plots)
        self.assertIn('waveform_tran.ready', script)
        self.assertNotIn('selectResults("dcOp-dc")', script)

    def test_op_only_uses_constant_waveform(self):
        config = {'cell': 'general', 'analysis': 'op',
                  'expressions': ['v("out")'], 'labels': ['out']}
        (self.root / 'capture_config.json').write_text(json.dumps(config), encoding='utf-8')
        cell, plots = capture._plot_settings(str(self.root))
        script = capture._script(str(self.root), 'vai_run123', str(self.out), cell, plots)
        self.assertEqual([p['analysis'] for p in plots], ['op'])
        self.assertIn('procedure(gConstant(value)', script)
        self.assertIn('selectResults("dcOp-dc")', script)
        self.assertIn('gConstant(v("out"))', script)

    def test_second_waveform_excludes_first_window(self):
        tree = '0x001 "ViVA - first"\n0x002 "ViVA - second"\n'
        self.assertEqual(capture._windows(tree, 'waveform_ac', 'vai_run123', {'0x001'}),
                         [('0x002', 'ViVA - second')])
        self.assertEqual(capture._capture_windows(tree, 'waveform_ac', 'vai_run123',
                                                   {'0x001'}, ('0x001', 'ViVA - first')),
                         [('0x002', 'ViVA - second')])

    def test_second_plot_may_reuse_the_same_viva_window(self):
        tree = '0x001 "ViVA - current plot"\n'
        self.assertEqual(capture._capture_windows(tree, 'waveform_ac', 'vai_run123',
                                                   {'0x001'}, ('0x001', 'ViVA - current plot')),
                         [('0x001', 'ViVA - current plot')])

    def test_each_native_export_is_normalized_and_required(self):
        source = self.out / 'waveform_ac_nativewindow0.png'
        source.write_bytes(b'png-data')
        capture._normalize_native(str(self.out), 'waveform_ac')
        self.assertFalse(source.exists())
        self.assertEqual((self.out / 'waveform_ac_native.png').read_bytes(), b'png-data')
        with self.assertRaisesRegex(capture.CaptureError, 'waveform_dc_native.png'):
            capture._normalize_native(str(self.out), 'waveform_dc')


if __name__ == '__main__':
    unittest.main()
