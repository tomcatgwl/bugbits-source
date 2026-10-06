"""Shared real bee VAN slots must reuse posed vertices before rasterizing."""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from bugbits import web_build


class AtlasPoseCache(unittest.TestCase):
    def test_shared_flight_slots_skin_three_unique_animations_once(self):
        images, stats, consumed = {}, {}, set()
        tile = Image.new('RGBA', (128,128), (1,2,3,255))
        with patch.object(web_build.pose, 'skin_at', wraps=web_build.pose.skin_at) as skin, \
                patch.object(web_build.bake, '_render_rgba', return_value=tile) as raster:
            clips, _ = web_build.render_unit_clips('bee', images, stats, consumed)
        # Original bee walk/idle share bee_flight; flight/attack/hurt each
        # reach the configured 16-frame cap. Only raster output is stubbed.
        self.assertEqual(clips['walk']['ref'], 'Bugs/bee_flight')
        self.assertEqual(clips['idle']['ref'], clips['walk']['ref'])
        self.assertEqual([clips[key]['frames'] for key in
                          ('walk','normal_attack','hurt')], [16,16,16])
        self.assertEqual(skin.call_count, 48)
        self.assertEqual(raster.call_count, 384)
        self.assertEqual(len(images), 384)
        self.assertEqual(clips['walk']['prefix'], clips['idle']['prefix'])
