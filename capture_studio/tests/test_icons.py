"""v10 icon set: every referenced icon is vendored, licensed and renders non-empty at every DPR in both themes."""
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from capture_studio import icons, theme  # noqa: E402

APP = QApplication.instance() or QApplication([])


def ink(pixmap):
    image = pixmap.toImage()
    return sum(1 for y in range(image.height()) for x in range(image.width()) if image.pixelColor(x, y).alpha() > 40)


class IconTests(unittest.TestCase):
    def tearDown(self):
        theme.DARK_MODE = False

    def test_files_and_license(self):
        folder = icons.icon_dir()
        self.assertTrue((folder / "LICENSE").read_text(encoding="utf-8").startswith("ISC License"))
        self.assertIn("Lucide", (folder / "ATTRIBUTION.md").read_text(encoding="utf-8"))
        for name in icons.referenced():
            self.assertTrue(icons.file_for(name).is_file(), name)

    def test_button_and_category_maps_point_at_known_names(self):
        for name in list(icons.BUTTON_ICONS.values()) + list(icons.CATEGORY_ICONS.values()):
            self.assertIn(name, icons.ICONS)

    def test_render_all_dprs_both_themes(self):
        for dark in (False, True):
            theme.DARK_MODE = dark
            for name in sorted(icons.ICONS):
                for size in icons.SIZES:
                    for dpr in icons.DPRS:
                        pm = icons.pixmap(name, size, "normal", dpr)
                        self.assertEqual(pm.width(), round(size * dpr), (name, size, dpr))
                        self.assertAlmostEqual(pm.devicePixelRatio(), dpr)
                        self.assertGreater(ink(pm), size // 2, (name, size, dpr, dark))

    def test_theme_and_state_colours(self):
        light = icons.role_color("normal")
        theme.DARK_MODE = True
        self.assertNotEqual(light, icons.role_color("normal"))
        self.assertEqual(icons.role_color("onAccent"), "#FFFFFF")
        self.assertNotEqual(icons.role_color("disabled"), icons.role_color("normal"))
        svg = icons.svg_bytes("nav.lab", "#123456", 1.75).decode()
        self.assertIn("#123456", svg)
        self.assertNotIn("currentColor", svg)
        self.assertIn('stroke-width="1.75"', svg)

    def test_qicon_has_hidpi_variants(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        qi = icons.icon("act.connect", 16)
        sizes = {(s.width(), s.height()) for s in qi.availableSizes(QIcon.Mode.Normal)}
        self.assertTrue({(16, 16), (20, 20), (24, 24), (32, 32)} <= sizes, sizes)
        self.assertFalse(qi.pixmap(QSize(16, 16), 1.25, QIcon.Mode.Disabled).isNull())

    def test_tiles_and_app_icon(self):
        for category, name in icons.CATEGORY_ICONS.items():
            for dpr in icons.DPRS:
                self.assertGreater(ink(icons.tile(name, 22, "#0071E3", dpr)), 100, category)
        for px in (16, 32, 256):
            self.assertGreater(ink(icons.app_pixmap(px)), px * px // 2)
        assets = Path(icons.__file__).parent / "assets"
        self.assertTrue((assets / "app.ico").stat().st_size > 1000)
        self.assertTrue((assets / "app.png").is_file())

    def test_chevron_has_2x_twin(self):
        import tempfile
        folder = Path(tempfile.mkdtemp())
        path = Path(icons.chevron_files(folder, "#86868B"))
        self.assertTrue(path.is_file())
        self.assertTrue(path.with_name(path.stem + "@2x.png").is_file())


if __name__ == "__main__":
    unittest.main()
