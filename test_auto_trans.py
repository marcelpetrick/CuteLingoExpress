"""
Unit tests for auto_trans.py.
These tests cover the main helpers and command-line behavior.
"""

import runpy
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import auto_trans
from version import VERSION, get_startup_banner, get_version


class VersionTests(unittest.TestCase):
    """Tests for version metadata and startup banners."""

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

    def test_get_version_returns_configured_version(self):
        """
        Test that get_version returns the configured semantic version string.
        """
        self.assertEqual(get_version(), VERSION)


class HelperFunctionTests(unittest.TestCase):  # pylint: disable=too-many-public-methods
    """Tests for standalone helper functions in auto_trans."""

    @patch("auto_trans.time.time", side_effect=[10.0, 10.01])
    def test_translate_string(self, _mock_time):
        """
        Test that translate_string calls the appropriate translation function
        and returns the correct result.
        """
        mock_translate_text = MagicMock(return_value="你好世界")

        with patch.dict(
            "sys.modules",
            {"translators": SimpleNamespace(translate_text=mock_translate_text)},
        ):
            result = auto_trans.translate_string("Hello world", "en", "cn")

        self.assertEqual(result, "你好世界")
        mock_translate_text.assert_called_once_with(
            "Hello world",
            translator="google",
            from_language="en",
            to_language="cn",
            timeout=auto_trans.TRANSLATION_TIMEOUT_SECONDS,
        )

    @patch("auto_trans.time.time", side_effect=[20.0, 22.345656356])
    @patch("builtins.print")
    def test_translate_string_truncates_duration_to_one_decimal(
        self,
        mock_print,
        _mock_time,
    ):
        """
        Test that translation timing output does not expose noisy precision.
        """
        mock_translate_text = MagicMock(return_value="你好世界")

        with patch.dict(
            "sys.modules",
            {"translators": SimpleNamespace(translate_text=mock_translate_text)},
        ):
            auto_trans.translate_string("Hello world", "en", "cn")

        mock_print.assert_called_once_with(
            "translateString[google]: 2.3s : Hello world -> 你好世界 (en -> cn)"
        )

    def test_translate_string_falls_back_to_next_backend(self):
        """
        Test that a transient primary backend failure uses the next backend.
        """
        mock_translate_text = MagicMock(side_effect=[RuntimeError("google failed"), "你好世界"])

        with patch.dict(
            "sys.modules",
            {"translators": SimpleNamespace(translate_text=mock_translate_text)},
        ):
            result = auto_trans.translate_string("Hello world", "en", "cn")

        self.assertEqual(result, "你好世界")
        self.assertEqual(
            [call.kwargs["translator"] for call in mock_translate_text.call_args_list],
            ["google", "bing"],
        )

    def test_translate_string_raises_after_all_backends_fail(self):
        """
        Test that backend failures are reported after the fallback chain is exhausted.
        """
        mock_translate_text = MagicMock(side_effect=RuntimeError("offline"))

        with patch.dict(
            "sys.modules",
            {"translators": SimpleNamespace(translate_text=mock_translate_text)},
        ):
            with self.assertRaisesRegex(
                auto_trans.TranslationBackendError,
                "All translation backends failed",
            ):
                auto_trans.translate_string("Hello world", "en", "cn")

        self.assertEqual(mock_translate_text.call_count, len(auto_trans.TRANSLATION_BACKENDS))

    def test_auto_source_skips_backend_without_detection(self):
        """
        Test that auto detection never reaches a backend that guesses Chinese.
        """
        mock_translate_text = MagicMock(side_effect=RuntimeError("offline"))

        with self.assertRaisesRegex(
            auto_trans.TranslationBackendError,
            "myMemory: source-language auto detection is unsupported",
        ):
            auto_trans.translate_with_configured_backends(
                SimpleNamespace(translate_text=mock_translate_text),
                "Hello world",
                "auto",
                "de",
            )

        self.assertEqual(
            [call.kwargs["translator"] for call in mock_translate_text.call_args_list],
            ["google", "bing"],
        )

    def test_format_translation_backends_reflects_auto_detection_support(self):
        """
        Test that the run summary reports only backends eligible for the source mode.
        """
        self.assertEqual(
            auto_trans.format_translation_backends("auto"),
            "google -> bing",
        )
        self.assertEqual(
            auto_trans.format_translation_backends("en"),
            "google -> bing -> myMemory",
        )

    def test_format_duration_seconds_truncates_to_one_decimal(self):
        """
        Test that duration formatting cuts extra precision instead of rounding.
        """
        self.assertEqual(auto_trans.format_duration_seconds(2.345656356), "2.3s")
        self.assertEqual(auto_trans.format_duration_seconds(0.01), "0.0s")

    def test_help_text_contains_description_and_example(self):
        """
        Test that the short help text includes a description and example usage.
        """
        help_text = auto_trans.get_help_text()

        self.assertIn("Translate unfinished entries in a Qt .ts file in place.", help_text)
        self.assertIn(
            "Usage: python auto_trans.py <ts_file_path> [source_language] [target_language]",
            help_text,
        )
        self.assertIn("Languages are read from Qt TS metadata", help_text)
        self.assertIn("python auto_trans.py testing/helloworld.ts en de", help_text)
        self.assertIn("--lvgl-yaml <yaml_file>", help_text)

    def test_normalize_qt_language_preserves_supported_locale_variants(self):
        """
        Test that generic locales use their language while supported variants survive.
        """
        self.assertEqual(auto_trans.normalize_qt_language("de_DE"), "de")
        self.assertEqual(auto_trans.normalize_qt_language("zh_CN"), "zh-CN")
        self.assertEqual(auto_trans.normalize_qt_language("fr-CA"), "fr-CA")

    def test_infer_target_language_from_filename(self):
        """
        Test conventional language and locale suffixes in TS filenames.
        """
        self.assertEqual(
            auto_trans.infer_target_language_from_filename("translations/app_de.ts"),
            "de",
        )
        self.assertEqual(
            auto_trans.infer_target_language_from_filename("translations/app_zh_CN.ts"),
            "zh-CN",
        )
        self.assertIsNone(
            auto_trans.infer_target_language_from_filename("translations/messages.ts")
        )

    def test_infer_source_and_target_languages_from_filename(self):
        """
        Test source-target pairs without confusing target locale suffixes.
        """
        self.assertEqual(
            auto_trans.infer_languages_from_filename("translations/app_en_de.ts"),
            ("en", "de"),
        )
        self.assertEqual(
            auto_trans.infer_languages_from_filename("translations/app_de_DE.ts"),
            (None, "de"),
        )

    def test_resolve_languages_prefers_explicit_values(self):
        """
        Test that user-provided languages override metadata and filenames.
        """
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix="_de.ts") as temp_file:
            temp_file.write('<TS language="fr_FR" sourcelanguage="en_US"></TS>')
            temp_file.flush()

            languages = auto_trans.resolve_languages(temp_file.name, "es", "it")

        self.assertEqual(languages, ("es", "it"))

    def test_resolve_languages_uses_ts_metadata(self):
        """
        Test source and target inference from Qt TS root attributes.
        """
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".ts") as temp_file:
            temp_file.write('<TS language="zh_CN" sourcelanguage="en_US"></TS>')
            temp_file.flush()

            languages = auto_trans.resolve_languages(temp_file.name)

        self.assertEqual(languages, ("en", "zh-CN"))

    def test_resolve_languages_uses_filename_and_auto_source(self):
        """
        Test filename target inference and backend source detection fallback.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            ts_path = Path(temp_dir) / "application_de.ts"
            ts_path.write_text('<TS version="2.1"></TS>', encoding="utf-8")

            languages = auto_trans.resolve_languages(ts_path)

        self.assertEqual(languages, ("auto", "de"))

    def test_resolve_languages_uses_source_target_filename_pair(self):
        """
        Test complete language inference from a filename pair.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            ts_path = Path(temp_dir) / "application_en_de.ts"
            ts_path.write_text('<TS version="2.1"></TS>', encoding="utf-8")

            languages = auto_trans.resolve_languages(ts_path)

        self.assertEqual(languages, ("en", "de"))

    def test_resolve_languages_requires_inferable_target(self):
        """
        Test that an ambiguous file requests an explicit target instead of guessing.
        """
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".ts") as temp_file:
            temp_file.write('<TS version="2.1"></TS>')
            temp_file.flush()

            with self.assertRaisesRegex(ValueError, "Unable to infer the target language"):
                auto_trans.resolve_languages(temp_file.name)

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
            written_content = Path(temp_file.name).read_text(encoding='utf-8')

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
            written_content = Path(temp_file.name).read_text(encoding='utf-8')

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

    def test_escape_ts_text_preserves_requested_quote_entities(self):
        """
        Test that translated text can preserve both quote styles when requested.
        """
        escaped_text = auto_trans.escape_ts_text(
            'Entry\'s "value" & more',
            preserve_double_quotes=True,
            preserve_single_quotes=True,
        )

        self.assertEqual(
            escaped_text,
            "Entry&apos;s &quot;value&quot; &amp; more",
        )

    def test_remove_unfinished_type_preserves_other_attributes(self):
        """
        Test that unfinished is removed while other translation attributes remain.
        """
        updated_attributes = auto_trans.remove_unfinished_type(
            ' type="unfinished" variants="yes" '
        )

        self.assertEqual(updated_attributes, ' variants="yes"')

    def test_remove_unfinished_type_returns_empty_string_when_no_attributes_remain(self):
        """
        Test that an empty attribute string stays empty after cleanup.
        """
        self.assertEqual(
            auto_trans.remove_unfinished_type(' type="unfinished"'),
            "",
        )

    def test_replace_translation_in_message_raises_for_missing_translation_block(self):
        """
        Test that malformed TS message blocks raise a descriptive error.
        """
        message_block = "<message><source>Hello</source></message>"

        with self.assertRaisesRegex(
            ValueError,
            "Unable to locate source or translation block",
        ):
            auto_trans.replace_translation_in_message(
                message_block,
                "Hallo",
                numerus=False,
            )

    def test_replace_translation_in_message_handles_numerus_entries(self):
        """
        Test that numerus messages fill the existing numerusform entries.
        """
        message_block = """    <message numerus="yes">
        <source>%n file(s)</source>
        <translation type="unfinished">
            <numerusform></numerusform>
            <numerusform></numerusform>
        </translation>
    </message>"""

        updated_block = auto_trans.replace_translation_in_message(
            message_block,
            "%n Datei(en)",
            numerus=True,
        )

        self.assertIn("<numerusform>%n Datei(en)</numerusform>", updated_block)
        self.assertEqual(updated_block.count("<numerusform>"), 2)
        self.assertNotIn('type="unfinished"', updated_block)

    def test_replace_translation_in_message_preserves_numerusform_count(self):
        """
        Test that Qt numerus translations keep their language-specific form count.
        """
        message_block = """    <message numerus="yes">
        <source>%n file(s)</source>
        <translation type="unfinished">
            <numerusform></numerusform>
            <numerusform></numerusform>
            <numerusform></numerusform>
        </translation>
    </message>"""

        updated_block = auto_trans.replace_translation_in_message(
            message_block,
            "%n Datei(en)",
            numerus=True,
        )

        self.assertEqual(updated_block.count("<numerusform>%n Datei(en)</numerusform>"), 3)
        self.assertEqual(updated_block.count("<numerusform>"), 3)
        self.assertNotIn('type="unfinished"', updated_block)

    def test_replace_translation_in_message_creates_single_numerusform_fallback(self):
        """
        Test the defensive fallback for malformed numerus messages without slots.
        """
        message_block = """    <message numerus="yes">
        <source>%n file(s)</source>
        <translation type="unfinished"></translation>
    </message>"""

        updated_block = auto_trans.replace_translation_in_message(
            message_block,
            "%n Datei(en)",
            numerus=True,
        )

        self.assertEqual(updated_block.count("<numerusform>%n Datei(en)</numerusform>"), 1)
        self.assertNotIn('type="unfinished"', updated_block)

    def test_update_ts_content_raises_when_message_count_changes(self):
        """
        Test that mismatched message counts fail instead of corrupting the file.
        """
        original_content = "<TS><message></message></TS>"

        with self.assertRaisesRegex(
            ValueError,
            "TS message count changed while processing the file",
        ):
            auto_trans.update_ts_content(original_content, [])

    def test_update_ts_content_preserves_missing_trailing_newline(self):
        """
        Test that rewriting preserves the absence of a trailing newline.
        """
        original_content = """<TS>
<message>
    <source>Hello</source>
    <translation type="unfinished"></translation>
</message>
</TS>"""
        updated_content = auto_trans.update_ts_content(
            original_content,
            [{"translated_text": "Hallo", "numerus": False}],
        )

        self.assertFalse(updated_content.endswith("\n"))

    def test_format_run_summary_includes_requested_statistics(self):
        """
        Test that the CLI summary prints version, counts, and runtime.
        """
        summary = auto_trans.format_run_summary(
            {
                "version": VERSION,
                "source_language": "en",
                "target_language": "de",
                "backend": "google -> bing -> myMemory",
                "messages_scanned": 12,
                "unfinished_before": 7,
                "translated_count": 5,
                "numerus_translated_count": 2,
                "skipped_count": 2,
                "average_translation_seconds": 0.567,
                "runtime_seconds": 2.567,
            }
        )

        self.assertEqual(
            summary,
            (
                "Run summary:\n"
                "CuteLingoExpress: https://github.com/marcelpetrick/CuteLingoExpress\n"
                f"Version: {VERSION}\n"
                "Language direction: en -> de\n"
                "Backend: google -> bing -> myMemory\n"
                "Messages scanned: 12\n"
                "Unfinished strings before: 7\n"
                "Translated strings: 5\n"
                "Numerus translations: 2\n"
                "Skipped strings: 2\n"
                "Average translation time: 0.5s\n"
                "Overall runtime: 2.5s"
            ),
        )


class TransformTsFileTests(unittest.TestCase):
    """Tests for transforming TS files in place."""

    @patch("auto_trans.translate_string", return_value="你好世界")
    def test_transform_ts_file(self, mock_translate_string):
        """
        Test that transform_ts_file updates a .ts file correctly.
        """
        content = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="zh_CN">
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
            stats = auto_trans.transform_ts_file(temp_file.name, "en", "cn")
            written_content = Path(temp_file.name).read_text(encoding='utf-8')

        mock_translate_string.assert_called_once_with("Hello world", "en", "cn")
        self.assertIn("<translation>你好世界</translation>", written_content)
        self.assertNotIn('type="unfinished"', written_content)
        self.assertEqual(
            {
                key: value for key, value in stats.items()
                if key != "average_translation_seconds"
            },
            {
                "messages_scanned": 1,
                "unfinished_before": 1,
                "translated_count": 1,
                "numerus_translated_count": 0,
                "skipped_count": 0,
            },
        )
        self.assertGreaterEqual(stats["average_translation_seconds"], 0.0)

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

            stats = auto_trans.transform_ts_file(str(temp_path), "en", "de")
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
        self.assertEqual(stats["unfinished_before"], 5)
        self.assertEqual(stats["translated_count"], 5)
        self.assertEqual(stats["numerus_translated_count"], 0)
        self.assertEqual(stats["skipped_count"], 0)
        self.assertGreaterEqual(stats["messages_scanned"], 5)
        self.assertGreaterEqual(stats["average_translation_seconds"], 0.0)

    @patch("auto_trans.translate_string", return_value="%n Datei(en)")
    def test_transform_ts_file_updates_unfinished_numerus_messages(
        self,
        mock_translate_string,
    ):
        """
        Test that unfinished numerus messages are translated and written back.
        """
        content = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="de_DE">
<context>
    <name>Example</name>
    <message numerus="yes">
        <source>%n file(s)</source>
        <translation type="unfinished">
            <numerusform></numerusform>
            <numerusform></numerusform>
        </translation>
    </message>
</context>
</TS>
"""
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".ts") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            stats = auto_trans.transform_ts_file(temp_file.name, "en", "de")
            written_content = Path(temp_file.name).read_text(encoding='utf-8')

        mock_translate_string.assert_called_once_with("%n file(s)", "en", "de")
        self.assertEqual(written_content.count("<numerusform>%n Datei(en)</numerusform>"), 2)
        self.assertNotIn('type="unfinished"', written_content)
        self.assertEqual(
            {
                key: value for key, value in stats.items()
                if key != "average_translation_seconds"
            },
            {
                "messages_scanned": 1,
                "unfinished_before": 1,
                "translated_count": 1,
                "numerus_translated_count": 1,
                "skipped_count": 0,
            },
        )
        self.assertGreaterEqual(stats["average_translation_seconds"], 0.0)

    def test_transform_ts_file_skips_finished_messages(self):
        """
        Test that finished singular and numerus messages are left untouched.
        """
        content = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="de_DE">
<context>
    <name>Example</name>
    <message>
        <source>Hello</source>
        <translation>Hallo</translation>
    </message>
    <message numerus="yes">
        <source>%n file(s)</source>
        <translation>
            <numerusform>%n Datei</numerusform>
            <numerusform>%n Dateien</numerusform>
        </translation>
    </message>
</context>
</TS>
"""
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".ts") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            with patch("auto_trans.translate_string") as mock_translate_string:
                stats = auto_trans.transform_ts_file(temp_file.name, "en", "de")
            written_content = Path(temp_file.name).read_text(encoding='utf-8')

        mock_translate_string.assert_not_called()
        self.assertIn("<translation>Hallo</translation>", written_content)
        self.assertIn("<numerusform>%n Datei</numerusform>", written_content)
        self.assertEqual(
            stats,
            {
                "messages_scanned": 2,
                "unfinished_before": 0,
                "translated_count": 0,
                "numerus_translated_count": 0,
                "skipped_count": 0,
                "average_translation_seconds": 0.0,
            },
        )


class CliTests(unittest.TestCase):
    """Tests for the command-line interface entrypoints."""

    @patch("sys.argv", ["auto_trans.py", "--version"])
    @patch("builtins.print")
    def test_main_prints_version_banner_first(self, mock_print):
        """
        Test that startup prints the application version before doing anything else.
        """
        auto_trans.main()
        mock_print.assert_called_once_with(get_startup_banner())

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

    @patch(
        "sys.argv",
        ["auto_trans.py", "translations/app_de.ts", "en", "de", "unexpected"],
    )
    @patch("builtins.print")
    def test_main_prints_help_for_excess_arguments(self, mock_print):
        """
        Test that excess positional arguments are rejected with usage details.
        """
        with self.assertRaises(SystemExit) as raised:
            auto_trans.main()
        self.assertEqual(raised.exception.code, 2)

        self.assertEqual(
            mock_print.call_args_list,
            [call(get_startup_banner()), call(auto_trans.get_help_text())],
        )

    @patch("auto_trans_yaml.translate_yaml_file", return_value=Path("osd_en_de.yaml"))
    @patch("sys.argv", ["auto_trans.py", "--lvgl-yaml", "osd_en.yaml", "en", "de"])
    @patch("builtins.print")
    def test_main_dispatches_optional_lvgl_yaml_mode(
        self,
        mock_print,
        mock_translate_yaml_file,
    ):
        """The explicit YAML flag should dispatch through the application command."""
        auto_trans.main()

        mock_translate_yaml_file.assert_called_once_with("osd_en.yaml", "en", "de")
        self.assertEqual(
            mock_print.call_args_list,
            [
                call(get_startup_banner()),
                call("LVGL YAML translation written to: osd_en_de.yaml"),
            ],
        )

    @patch("sys.argv", ["auto_trans.py", "--lvgl-yaml", "osd_en.yaml"])
    @patch("builtins.print")
    def test_main_rejects_incomplete_lvgl_yaml_mode(self, mock_print):
        """Incomplete YAML invocations should print the shared application help."""
        with self.assertRaises(SystemExit) as raised:
            auto_trans.main()
        self.assertEqual(raised.exception.code, 2)

        self.assertEqual(
            mock_print.call_args_list,
            [call(get_startup_banner()), call(auto_trans.get_help_text())],
        )

    @patch("auto_trans.time.time", side_effect=[10.0, 12.5])
    @patch(
        "auto_trans.transform_ts_file",
        return_value={
            "messages_scanned": 0,
            "unfinished_before": 0,
            "translated_count": 0,
            "numerus_translated_count": 0,
            "skipped_count": 0,
            "average_translation_seconds": 0.0,
        },
    )
    @patch("auto_trans.resolve_languages", return_value=("auto", "de"))
    @patch("sys.argv", ["auto_trans.py", "translations/app_de.ts"])
    @patch("builtins.print")
    def test_main_infers_languages_for_path_only(
        self,
        mock_print,
        mock_resolve_languages,
        mock_transform_ts_file,
        _mock_time,
    ):
        """
        Test that path-only invocation resolves languages before translating.
        """
        auto_trans.main()

        mock_resolve_languages.assert_called_once_with(
            "translations/app_de.ts",
            None,
            None,
        )
        mock_transform_ts_file.assert_called_once_with(
            "translations/app_de.ts",
            "auto",
            "de",
        )
        self.assertEqual(mock_print.call_args_list[0], call(get_startup_banner()))
        self.assertIn("Backend: google -> bing\n", mock_print.call_args_list[1].args[0])

    @patch("auto_trans.time.time", side_effect=[10.0, 12.5])
    @patch(
        "auto_trans.transform_ts_file",
        return_value={
            "messages_scanned": 10,
            "unfinished_before": 4,
            "translated_count": 4,
            "numerus_translated_count": 1,
            "skipped_count": 0,
            "average_translation_seconds": 0.456,
        },
    )
    @patch("auto_trans.resolve_languages", return_value=("en", "de"))
    @patch("sys.argv", ["auto_trans.py", "testing/helloworld.ts", "en", "de"])
    @patch("builtins.print")
    def test_main_runs_translation_and_prints_duration(
        self,
        mock_print,
        mock_resolve_languages,
        mock_transform_ts_file,
        _mock_time,
    ):
        """
        Test that the CLI runs the translation flow and reports execution time.
        """
        auto_trans.main()

        mock_resolve_languages.assert_called_once_with(
            "testing/helloworld.ts",
            "en",
            "de",
        )
        mock_transform_ts_file.assert_called_once_with("testing/helloworld.ts", "en", "de")
        self.assertEqual(
            mock_print.call_args_list,
            [
                call(get_startup_banner()),
                call(
                    "Run summary:\n"
                    "CuteLingoExpress: https://github.com/marcelpetrick/CuteLingoExpress\n"
                    f"Version: {VERSION}\n"
                    "Language direction: en -> de\n"
                    "Backend: google -> bing -> myMemory\n"
                    "Messages scanned: 10\n"
                    "Unfinished strings before: 4\n"
                    "Translated strings: 4\n"
                    "Numerus translations: 1\n"
                    "Skipped strings: 0\n"
                    "Average translation time: 0.4s\n"
                    "Overall runtime: 2.5s"
                ),
            ],
        )

    @patch("builtins.print")
    def test_running_module_as_script_calls_main(self, mock_print):
        """
        Test that executing auto_trans.py as __main__ triggers the CLI entrypoint.
        """
        with patch("sys.argv", ["auto_trans.py", "--help"]):
            runpy.run_path(Path("auto_trans.py"), run_name="__main__")

        self.assertEqual(
            mock_print.call_args_list,
            [call(get_startup_banner()), call(auto_trans.get_help_text())],
        )


if __name__ == "__main__":
    unittest.main()
