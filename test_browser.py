import ast
import unittest
from pathlib import Path


class SourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).with_name("browser.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_source_parses(self):
        self.assertIsInstance(self.tree, ast.Module)

    def test_private_profile_is_explicit(self):
        self.assertIn("QWebEngineProfile(QApplication.instance())", self.source)
        self.assertIn("NoPersistentCookies", self.source)
        self.assertIn("MemoryHttpCache", self.source)

    def test_security_guards_are_present(self):
        self.assertIn('"HyperlinkAuditingEnabled", False', self.source)
        self.assertIn('"LocalContentCanAccessRemoteUrls", False', self.source)
        self.assertNotIn("ignoreCertificateError", self.source)

    def test_media_diagnostics_are_present(self):
        self.assertIn("video.canPlayType", self.source)
        self.assertIn("webengine-proprietary-codecs", self.source)


if __name__ == "__main__":
    unittest.main()
