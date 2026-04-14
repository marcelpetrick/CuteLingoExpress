"""
Unit tests for auto_trans.py.
These tests cover the main helpers and command-line behavior.
"""

import shutil
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, call, patch
from xml.etree import ElementTree

import auto_trans
from version import VERSION, get_startup_banner


class AutoTransTest(unittest.TestCase):
    """Tests for the auto_trans module."""

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

    @patch("auto_trans.translate_string", return_value="你好世界")
    def test_transform_ts_file(self, mock_translate_string):
        """
        Test that transform_ts_file updates a .ts file correctly.
        """
        content = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="de_DE">
<context>
    <name>QPushButton</name>
    <message>
        <source>Hello world</source>
        <translation type="unfinished"/>
    </message>
</context>
</TS>
"""
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".ts") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            auto_trans.transform_ts_file(temp_file.name, "en", "cn")
            temp_file.seek(0)
            written_content = temp_file.read()

        mock_translate_string.assert_called_once_with("Hello world", "en", "cn")
        self.assertIn("<translation>你好世界</translation>", written_content)
        self.assertNotIn('type="unfinished"', written_content)

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

    def test_write_ts_tree_preserves_apostrophe_entities_in_text(self):
        """
        Test that apostrophes stay encoded as ``&apos;`` in Qt TS text content.
        """
        tree = ElementTree.ElementTree(ElementTree.Element("TS"))
        message = ElementTree.SubElement(tree.getroot(), "message")
        source = ElementTree.SubElement(message, "source")
        translation = ElementTree.SubElement(message, "translation")
        text = 'Entry\'s "%1" attribute copied to the clipboard!'
        source.text = text
        translation.text = text

        with tempfile.NamedTemporaryFile("r+", encoding="utf-8", suffix=".ts") as temp_file:
            auto_trans.write_ts_tree(tree, temp_file.name)
            temp_file.seek(0)
            written_content = temp_file.read()

        self.assertIn(
            "Entry&apos;s &quot;%1&quot; attribute copied to the clipboard!",
            written_content,
        )
        self.assertNotIn('Entry\'s "%1" attribute copied to the clipboard!', written_content)

    @patch("auto_trans.translate_string", return_value='Er sagte "Hallo"')
    def test_transform_ts_file_preserves_untouched_source_entities(self, mock_translate_string):
        """
        Test that untouched source strings keep their original entity spelling.
        """
        content = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="de_DE">
<context>
    <name>Example</name>
    <message>
        <source>Don&apos;t expose this database</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>The attachment '%1' was modified.</source>
        <translation>Existing translation</translation>
    </message>
</context>
</TS>
"""
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".ts") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            auto_trans.transform_ts_file(temp_file.name, "en", "de")
            temp_file.seek(0)
            written_content = temp_file.read()

        mock_translate_string.assert_called_once_with("Don't expose this database", "en", "de")
        self.assertIn("<source>Don&apos;t expose this database</source>", written_content)
        self.assertNotIn("<source>Don't expose this database</source>", written_content)
        self.assertIn("<source>The attachment '%1' was modified.</source>", written_content)
        self.assertNotIn("&apos;%1&apos;", written_content)

    @patch(
        "auto_trans.translate_string",
        return_value='<html><span style=" font-weight:600;">Hallo</span></html>',
    )
    def test_transform_ts_file_matches_source_quote_style_for_new_translation(
        self,
        mock_translate_string,
    ):
        """
        Test that new translations reuse the entity style found in the source text.
        """
        content = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="de_DE">
<context>
    <name>Example</name>
    <message>
        <source>&lt;html&gt;&lt;span style=&quot; font-weight:600;&quot;&gt;Hi&lt;/span&gt;&lt;/html&gt;</source>
        <translation type="unfinished"></translation>
    </message>
</context>
</TS>
"""
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".ts") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            auto_trans.transform_ts_file(temp_file.name, "en", "de")
            temp_file.seek(0)
            written_content = temp_file.read()

        mock_translate_string.assert_called_once_with(
            '<html><span style=" font-weight:600;">Hi</span></html>',
            "en",
            "de",
        )
        self.assertIn(
            (
                "&lt;html&gt;&lt;span style=&quot; font-weight:600;&quot;&gt;"
                "Hallo&lt;/span&gt;&lt;/html&gt;"
            ),
            written_content,
        )

    def test_keepassxc_fixture_contains_mixed_quote_styles(self):
        """
        Test that the KeePassXC fixture covers both entity and literal apostrophe styles.
        """
        fixture_content = Path("testing/keepassxc_de.ts").read_text(encoding="utf-8")

        self.assertIn(
            "Entry&apos;s &quot;%1&quot; attribute copied to the clipboard!",
            fixture_content,
        )
        self.assertIn("The attachment '%1' was modified.", fixture_content)

    @patch(
        "auto_trans.translate_string",
        side_effect=lambda source, _src, _dst: f"TRANSLATED: {source}",
    )
    def test_transform_ts_file_preserves_keepassxc_fixture_quote_style(
        self,
        mock_translate_string,
    ):
        """
        Test that the real KeePassXC fixture can be transformed without mangling
        apostrophes or quotes in untouched strings.
        """
        fixture_path = Path("testing/keepassxc_de.ts")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / fixture_path.name
            shutil.copyfile(fixture_path, temp_path)

            auto_trans.transform_ts_file(str(temp_path), "en", "de")
            written_content = temp_path.read_text(encoding="utf-8")

        self.assertEqual(mock_translate_string.call_count, 5)
        self.assertIn(
            "Entry&apos;s &quot;%1&quot; attribute copied to the clipboard!",
            written_content,
        )
        self.assertIn("The attachment '%1' was modified.", written_content)
        self.assertNotIn(
            "Entry's &quot;%1&quot; attribute copied to the clipboard!",
            written_content,
        )
        self.assertNotIn("The attachment &apos;%1&apos; was modified.", written_content)
        self.assertIn(
            "<translation>TRANSLATED: Auto-generate password for new entries</translation>",
            written_content,
        )
        self.assertIn(
            "<translation>TRANSLATED: Failed to read string data: %1</translation>",
            written_content,
        )
        self.assertNotIn('type="unfinished"', written_content)

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
