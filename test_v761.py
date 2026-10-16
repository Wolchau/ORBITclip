"""Geometry, settings compatibility and negative-coordinate secondary monitors."""
import ast
import unittest
from pathlib import Path
from orbit_version import CLIENT_VERSION
from orbit_drum_layout import (DEFAULTS, SHAPES, POSITIONS, HEADERS,
                               normalize_options, place_popup, shape_size)
from orbit_drum_geometry import visible_faces


class DrumLayoutTests(unittest.TestCase):
    def test_761_version_defaults_and_shapes(self):
        self.assertEqual(CLIENT_VERSION, "7.8.0")
        self.assertEqual(len(SHAPES),4)
        self.assertEqual(shape_size(None), (318,226))
        self.assertLess(shape_size({"shape":"compact"})[0],shape_size({"shape":"classic"})[0])
        self.assertGreater(shape_size({"shape":"wide"})[0],shape_size({"shape":"classic"})[0])
        self.assertLess(shape_size({"shape":"ribbon"})[1],shape_size({"shape":"compact"})[1])
        self.assertEqual(normalize_options({"opacity":999,"neighbors":30})["neighbors"],4)
        self.assertEqual(normalize_options({"opacity":999})["opacity"],100)
        self.assertEqual(normalize_options({"opacity":"bad"})["opacity"],92)
        self.assertEqual(normalize_options({"header":"hidden"})["header"],"hidden")
        self.assertEqual(normalize_options({"shape":"unknown"})["shape"],"compact")

    def test_four_neighbors_are_projected_and_sort_correctly(self):
        faces=visible_faces(0,count=30,extent=5,step_degrees=76/(4+.53),
                            half_degrees=76/(4+.53)*.45)
        displayed={round(f["relative"]) for f in faces if abs(f["relative"])<=4.4}
        self.assertEqual(displayed,set(range(-4,5)))

    def test_secondary_left_monitor_and_cursor_above(self):
        # The primary screen occupies x=0..1919. This secondary is LEFT of it.
        secondary=(-2560,-120,2560,1440)
        x,y=place_popup(secondary,(-1370,850),(390,302),"cursor_above")
        self.assertLess(x,0)
        self.assertEqual(y,527)
        self.assertGreaterEqual(x,secondary[0])
        self.assertLessEqual(x+390,0)
        # A secondary screen above the primary also uses signed coordinates.
        upper=(0,-1080,1920,1080)
        ax,ay=place_popup(upper,(800,-430),(318,226),"auto")
        self.assertLess(ay,0)
        self.assertTrue(-1080<=ay<=-226)

    def test_cursor_edge_and_center_on_target_screen(self):
        area=(1920,0,1920,1080)
        x,y=place_popup(area,(3800,20),(550,186),"cursor_above")
        self.assertTrue(1920<=x<=3840-550)
        self.assertTrue(0<=y<=1080-186)
        cx,cy=place_popup(area,(2000,400),(550,186),"screen_center")
        self.assertEqual((cx,cy),(2605,447))

    def test_settings_wiring_persists(self):
        source=(Path(__file__).parent/"orbitclip.py").read_text("utf-8")
        ast.parse(source)
        self.assertIn("self.drum_options=normalize_drum_options(",source)
        self.assertIn("drum_options=self.drum_options",source)
        self.assertIn("def set_drum_option(self,key,value)",source)
        self.assertIn("self.bubble.set_options(validated)",source)


if __name__=="__main__":unittest.main()
