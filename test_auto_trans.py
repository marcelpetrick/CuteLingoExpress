"""
Unit tests for auto_trans.py.
These tests cover the functions replace_first_lines, translate_string and transform_ts_file.
"""

import unittest
import tempfile
from unittest.mock import patch, MagicMock
from xml.etree import ElementTree
from types import SimpleNamespace
from unittest.mock import call

import auto_trans
from cutelingoexpress_version import VERSION, get_startup_banner


class AutoTransTest(unittest.TestCase):
    """
    Test class for the auto_trans module.
    """

    def setUp(self):
        """
        Set up anything that is necessary for the test environment.
        """

    @patch("builtins.open", new_callable=MagicMock)
    def test_replace_first_lines(self, mock_open):
        """
        Test that replace_first_lines replaces the first two lines of a file correctly.
        """
        auto_trans.replace_first_lines("fakepath")
        mock_open.assert_called_with("fakepath", 'r+', encoding='utf-8')

    def test_translate_string(self):
        """
        Test that translate_string calls the appropriate translation function
        and returns the correct result.
        """
        mock_google = MagicMock(return_value="你好世界")

        with patch.dict("sys.modules", {"translators": SimpleNamespace(google=mock_google)}):
            result = auto_trans.translate_string("Hello world", "en", "cn")

        self.assertEqual(result, "你好世界")
        mock_google.assert_called_once_with("Hello world", "en", "cn")

    @patch("xml.etree.ElementTree.parse")
    @patch("auto_trans.translate_string", return_value="你好世界")
    @patch("auto_trans.replace_first_lines")
    def test_transform_ts_file(self, mock_replace_first_lines, mock_translate_string, mock_parse):
        """
        Test that transform_ts_file updates a .ts file correctly.
        """
        fake_tree = ElementTree.ElementTree(ElementTree.Element("TS"))
        fake_msg = ElementTree.Element("message")
        fake_source = ElementTree.Element("source")
        fake_source.text = "Hello world"
        fake_translation = ElementTree.Element("translation", attrib={"type": "unfinished"})
        fake_msg.extend([fake_source, fake_translation])
        fake_tree.getroot().append(fake_msg)
        mock_parse.return_value = fake_tree

        auto_trans.transform_ts_file("fakepath", "en", "cn")

        mock_translate_string.assert_called_once_with("Hello world", "en", "cn")
        mock_replace_first_lines.assert_called_once_with("fakepath")
        self.assertIsNone(fake_translation.attrib.get('type'))
        self.assertEqual(fake_translation.text, "你好世界")

    def test_version_is_semver(self):
        """
        Test that the central application version follows semantic versioning.
        """
        self.assertRegex(VERSION, r"^\d+\.\d+\.\d+$")

    def test_startup_banner_contains_version(self):
        """
        Test that the startup banner surfaces the configured version.
        """
        self.assertEqual(get_startup_banner(), f"CuteLingoExpress {VERSION}")

    def test_help_text_contains_description_and_example(self):
        """
        Test that the short help text includes a description and example usage.
        """
        help_text = auto_trans.get_help_text()

        self.assertIn("Translate unfinished entries in a Qt .ts file in place.", help_text)
        self.assertIn("Usage: python auto_trans.py", help_text)
        self.assertIn("python auto_trans.py testing/helloworld.ts en cn", help_text)

    @patch("sys.argv", ["auto_trans.py", "--version"])
    @patch("builtins.print")
    def test_main_prints_version_banner_first(self, mock_print):
        """
        Test that startup prints the application version before doing anything else.
        """
        auto_trans.main()
        mock_print.assert_called_once_with(get_startup_banner())

    def test_write_ts_tree_preserves_quoted_entities_in_text(self):
        """
        Test that Qt HTML snippets keep ``&quot;`` instead of being normalized to ``"``.
        """
        tree = ElementTree.ElementTree(ElementTree.Element("TS"))
        message = ElementTree.SubElement(tree.getroot(), "message")
        source = ElementTree.SubElement(message, "source")
        translation = ElementTree.SubElement(message, "translation")
        html = (
            '<html><body><p><span style=" font-weight:600;">%1 </span>'
            'is requesting access</p></body></html>'
        )
        source.text = html
        translation.text = html

        with tempfile.NamedTemporaryFile("r+", encoding="utf-8", suffix=".ts") as temp_file:
            auto_trans.write_ts_tree(tree, temp_file.name)
            temp_file.seek(0)
            written_content = temp_file.read()

        self.assertIn("style=&quot; font-weight:600;&quot;", written_content)
        self.assertNotIn('style=" font-weight:600;"', written_content)

    @patch("sys.argv", ["auto_trans.py"])
    @patch("builtins.print")
    def test_main_prints_help_for_naked_invocation(self, mock_print):
        """
        Test that running without arguments prints the short help message.
        """
        auto_trans.main()

        self.assertEqual(
            mock_print.call_args_list,
            [call(get_startup_banner()), call(auto_trans.get_help_text())]
        )

    @patch("sys.argv", ["auto_trans.py", "--help"])
    @patch("builtins.print")
    def test_main_prints_help_for_explicit_help_flag(self, mock_print):
        """
        Test that --help prints the same short help message.
        """
        auto_trans.main()

        self.assertEqual(
            mock_print.call_args_list,
            [call(get_startup_banner()), call(auto_trans.get_help_text())]
        )


if __name__ == "__main__":
    unittest.main()
