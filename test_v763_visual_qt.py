"""Offscreen visual contracts and optional PNG gallery for CI artifacts.

A structural pixel test is more resilient across Windows/macOS font renderers
than exact-image hashes. Captured PNGs allow deliberate human visual review.
"""
import os
from pathlib import Path
import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage,QPainter
    from PySide6.QtWidgets import QApplication,QWidget
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,"PySide6 unavailable")
class DrumVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        cls.qt=QApplication.instance() or QApplication([])

    def test_pixel_invariants_and_capture(self):
        from orbit_drum import DrumBubble
        from orbit_drum_layout import SHAPES
        from orbit_appearance import palette
        class App:pass
        app=App()
        app.clock=QWidget()
        app.clock.resize(150,60)
        app.palette=palette("midnight")
        app.drum_style="minimal"
        app.animate_drum_categories=False
        app.drum_options={"shape":"classic","header":"hidden",
                          "opacity":100,"neighbors":2}
        drum=DrumBubble(app)
        items=[{"id":i,"text":f"Test item {i}: SELECT data FROM table"} for i in range(9)]
        output_dir=os.environ.get("ORBIT_CAPTURE_DIR")
        if output_dir:Path(output_dir).mkdir(parents=True,exist_ok=True)

        def render():
            self.qt.processEvents()
            img=QImage(drum.size(),QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            painter=QPainter(img)
            drum.render(painter)
            painter.end()
            return img

        try:
            drum.show_neighbors(items,4,"Все записи")
            for shape,(name,(w,h)) in SHAPES.items():
                for theme in ("midnight","light"):
                    app.palette=palette(theme)
                    for material in ("minimal","glass"):
                        drum.set_style(material)
                        drum.set_options({"shape":shape,"header":"hidden",
                                          "opacity":100,"neighbor_opacity":65,
                                          "neighbors":3,"neighbor_gap":20})
                        img=render()
                        self.assertEqual((img.width(),img.height()),(w,h))
                        self.assertEqual(img.pixelColor(0,0).alpha(),0)
                        self.assertGreater(img.pixelColor(w//2,h//2).alpha(),20)
                        if output_dir:
                            filename=f'{shape}_{theme}_{material}.png'
                            self.assertTrue(img.save(str(Path(output_dir)/filename)))
            drum.set_style("minimal")
            app.palette=palette("midnight")
            drum.set_options({"shape":"classic","header":"hidden",
                              "opacity":100,"neighbors":2})
            opaque=render().pixelColor(195,158).alpha()
            drum.set_options({"shape":"classic","header":"hidden",
                              "opacity":35,"neighbors":2})
            faded=render().pixelColor(195,158).alpha()
            self.assertGreater(opaque,80)
            self.assertLess(faded,opaque-30)

            drum.set_options({"shape":"classic","header":"hidden"})
            without=render()
            drum.set_options({"shape":"classic","header":"full"})
            with_header=render()
            self.assertEqual(without.pixelColor(40,20).alpha(),0)
            self.assertGreater(with_header.pixelColor(40,20).alpha(),50)
        finally:
            drum.close();app.clock.close()


if __name__=="__main__":unittest.main()
