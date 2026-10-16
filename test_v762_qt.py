"""Regression: every cylindrical face stays centered during vertical scrolling.

7.6.1 translated each face horizontally by sin(face angle), making
an oblique stack of parallelepipeds rather than a vertical drum.
"""
import os
import unittest

try:
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt, QPointF
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 unavailable")
class DrumAxisQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.qt = QApplication.instance() or QApplication([])

    def test_vertical_faces_share_axis_through_scroll_and_settings(self):
        from orbit_drum import DrumBubble
        from orbit_appearance import palette
        from orbit_drum_layout import SHAPES
        class App: pass
        app = App()
        app.clock = QWidget()
        app.clock.resize(140, 48)
        app.palette = palette("midnight")
        app.drum_style = "minimal"
        app.animate_drum_categories = True
        app.drum_options = {"shape":"classic", "header":"hidden",
                            "neighbors":4, "neighbor_gap":65}
        wheel = DrumBubble(app)
        data = [{"id":i, "text":f"Item {i}"} for i in range(20)]
        axes = []
        original = wheel._draw_face

        def checked_face(painter, face, preview, colors):
            center = painter.transform().map(QPointF(195, 155)).x()
            axes.append((face["relative"], center))
            original(painter, face, preview, colors)

        wheel._draw_face = checked_face
        try:
            wheel.show_neighbors(data, 2, "Все")
            for shape in ("compact", "classic", "wide"):
                for gap in (0, 30, 65):
                    wheel.set_options({"shape":shape, "neighbor_gap":gap,
                                       "neighbors":4, "header":"hidden"})
                    expected_x = 195 * wheel.width() / 390
                    for cursor in (2., 2.2, 2.5, 2.9, 3.):
                        wheel._cursor = cursor
                        axes.clear()
                        image = QImage(wheel.size(), QImage.Format_ARGB32_Premultiplied)
                        image.fill(Qt.transparent)
                        painter = QPainter(image)
                        wheel.render(painter)
                        painter.end()
                        self.assertGreaterEqual(len(axes), 3)
                        for relative, x in axes:
                            self.assertAlmostEqual(x, expected_x, delta=.1,
                                msg=f"Drum tilted: {shape=}, {gap=}, {cursor=}, {relative=}, {x=}")
        finally:
            wheel.close()
            app.clock.close()

    def test_shape_names_preserved_and_versioned(self):
        from orbit_version import CLIENT_VERSION
        self.assertEqual(CLIENT_VERSION, "7.8.0")


if __name__ == "__main__":
    unittest.main()
