import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_server import display_url
from dashboard import clickable


class TestServerBanner(unittest.TestCase):
    def test_display_url_uses_localhost_for_bind_addresses(self):
        # 0.0.0.0 / :: are bind addresses — a browser can't open them, so the
        # printed link must point at localhost to be clickable.
        self.assertEqual(display_url("0.0.0.0", 5000), "http://localhost:5000")
        self.assertEqual(display_url("::", 8080), "http://localhost:8080")

    def test_display_url_keeps_specific_hosts(self):
        self.assertEqual(display_url("192.168.1.5", 5000), "http://192.168.1.5:5000")
        self.assertEqual(display_url("localhost", 5000), "http://localhost:5000")

    def test_clickable_wraps_url_in_osc8_hyperlink(self):
        link = clickable("http://localhost:5000")
        self.assertIn("\x1b]8;;http://localhost:5000\x1b\\", link)
        self.assertIn("http://localhost:5000\x1b]8;;\x1b\\", link)


if __name__ == "__main__":
    unittest.main()
