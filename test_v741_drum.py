"""Regression tests for the 7.4.1 frameless, animated drum (no Qt required)."""
import ast
import math
import unittest
from pathlib import Path

from orbit_drum_geometry import face_geometry, next_target, visible_faces
from orbit_version import CLIENT_VERSION

ROOT = Path(__file__).resolve().parent


class ProjectionTests(unittest.TestCase):
    def test_version_and_selection_unwrap(self):
        self.assertEqual(CLIENT_VERSION, '7.4.1')
        self.assertEqual(next_target(4, 0, 5, 1), 5)
        self.assertEqual(next_target(0, 4, 5, -1), -1)
        self.assertEqual(next_target(0, 1, 2, -1), -1)
        self.assertEqual(next_target(1, 0, 2, 1), 2)
        self.assertEqual(next_target(6, 0, 7, 1), 7)
        self.assertEqual(next_target(0, 0, 1, 1), 0)

    def test_projected_height_and_shading_follow_cylinder(self):
        middle = face_geometry(0)
        upper = face_geometry(-1)
        lower = face_geometry(1)
        self.assertIsNotNone(middle)
        self.assertLess(upper['top_y'], middle['top_y'])
        self.assertGreater(lower['bottom_y'], middle['bottom_y'])
        self.assertLess(upper['height'], middle['height'])
        self.assertLess(lower['opacity'], middle['opacity'])
        self.assertAlmostEqual(upper['height'], lower['height'], places=8)
        self.assertIsNone(face_geometry(2))

    def test_continuity_and_center_selection_during_animation(self):
        for cursor in [0, 0.1, .5, .9, 1, 6.3]:
            faces = visible_faces(cursor, count=5)
            self.assertGreaterEqual(len(faces), 2)
            self.assertTrue(all(f['height'] > 0 for f in faces))
            center = min(faces, key=lambda f: abs(f['relative']))
            self.assertEqual(center['index'], round(cursor) % 5)
            self.assertTrue(all(0 <= f['opacity'] <= 1 for f in faces))

    def test_no_rectangular_popup_or_flickering_recreation(self):
        code=(ROOT/'orbit_drum.py').read_text('utf-8')
        self.assertIn('Qt.WA_TranslucentBackground',code)
        self.assertIn('Qt.FramelessWindowHint',code)
        self.assertIn('Qt.WindowTransparentForInput',code)
        self.assertIn('QVariantAnimation',code)
        self.assertIn('QEasingCurve.OutCubic',code)
        self.assertNotIn('p.drawRoundedRect(self.rect()',code)
        core=(ROOT/'orbitclip.py').read_text('utf-8')
        self.assertIn('self.draw_bubble(value)',core)
        self.assertIn('step_hint=wheel_step',core)


if __name__ == '__main__':
    unittest.main()
