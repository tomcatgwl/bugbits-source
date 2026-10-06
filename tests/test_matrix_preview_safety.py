import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research'))
spec=importlib.util.spec_from_file_location('matrix_preview',ROOT/'research/linux_matrix_browser_preview.py')
preview=importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class MatrixPreviewSafety(unittest.TestCase):
    def test_traversal_is_refused_before_directory_claim(self):
        dangerous=ROOT/'out/linux-continuation/../../../outside-preview'
        # Block ALL claims: the red version must never actually write outside.
        with patch.object(Path,'mkdir',side_effect=RuntimeError('directory claim reached')) as claim:
            with self.assertRaises(ValueError):
                preview.run(dangerous)
            claim.assert_not_called()

    def test_snapshot_and_consumed_file_use_same_single_read(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp/linux/runtime') as temp:
            target=Path(temp)/'asset'; snapshot=Path(temp)/'snapshot'
            source=ROOT/'web/camera_projection.js'
            with patch.object(Path,'read_bytes',side_effect=[b'first',b'changed']) as reads:
                digest=preview.copy_sealed(source,target,snapshot)
            self.assertEqual(reads.call_count,1)
            self.assertEqual(target.read_bytes(),b'first')
            self.assertEqual(snapshot.read_bytes(),b'first')
            self.assertEqual(digest,preview.hashlib.sha256(b'first').hexdigest())
