"""Regression tests for issues found in the repository review."""

import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import auto_trans


TS_SAMPLE = '''<TS language="de_DE"><context><name>Example</name>
<message>
<source>Hello</source>
<translation type="unfinished"/>
</message>
</context></TS>
'''


class AtomicTsWriteTests(unittest.TestCase):
    """A failed output operation must never destroy the input catalog."""

    def test_write_failure_preserves_original_and_cleans_temporary_file(self):
        """Both write and replacement failures leave the source bytes intact."""
        original_factory = tempfile.NamedTemporaryFile

        def failing_writer(*args, **kwargs):
            # The production caller owns and closes this injected context manager.
            handle = original_factory(*args, **kwargs)  # pylint: disable=consider-using-with
            handle.write = lambda _content: self.fail_write()
            return handle

        for failure in ('write', 'replace'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'app_de.ts'
                path.write_text(TS_SAMPLE, encoding='utf-8')
                target = ('auto_trans.NamedTemporaryFile' if failure == 'write'
                          else 'auto_trans.Path.replace')
                effect = failing_writer if failure == 'write' else OSError('disk full')
                with patch(target, side_effect=effect, create=True), patch(
                    'auto_trans.translate_string', return_value='Hallo'
                ):
                    with self.assertRaises(OSError):
                        auto_trans.transform_ts_file(path, 'en', 'de')
                self.assertEqual(path.read_text(encoding='utf-8'), TS_SAMPLE)
                self.assertEqual(list(Path(directory).iterdir()), [path])

    @staticmethod
    def fail_write():
        """Simulate a filesystem refusing an output write."""
        raise OSError('disk full')

    def test_successful_write_preserves_mode_and_symlink(self):
        """Atomic replacement keeps permissions and updates a symlink's target."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app_de.ts'
            path.write_text(TS_SAMPLE, encoding='utf-8')
            path.chmod(0o640)
            link = Path(directory) / 'link.ts'
            link.symlink_to(path)
            with patch('auto_trans.translate_string', return_value='Hallo'):
                auto_trans.transform_ts_file(link, 'en', 'de')
            self.assertTrue(link.is_symlink())
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertIn('<translation>Hallo</translation>', path.read_text(encoding='utf-8'))


class CatalogLanguageTests(unittest.TestCase):
    """An explicit target cannot silently mix languages in an existing catalog."""

    def test_mismatched_target_is_rejected_before_translation_or_write(self):
        """Finished entries and root metadata remain consistent with new entries."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app_de.ts'
            path.write_text(TS_SAMPLE, encoding='utf-8')
            with patch('auto_trans.translate_string', return_value='你好') as translator:
                with self.assertRaisesRegex(ValueError, 'catalog language'):
                    auto_trans.transform_ts_file(path, 'en', 'cn')
                translator.assert_not_called()
            self.assertEqual(path.read_text(encoding='utf-8'), TS_SAMPLE)

    def test_matching_chinese_alias_is_accepted(self):
        """The backend alias cn is equivalent to Qt's zh_CN locale."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app_zh_CN.ts'
            path.write_text(TS_SAMPLE.replace('de_DE', 'zh_CN'), encoding='utf-8')
            with patch('auto_trans.translate_string', return_value='你好'):
                auto_trans.transform_ts_file(path, 'en', 'cn')
            self.assertIn('你好', path.read_text(encoding='utf-8'))


class PipelineImportTests(unittest.TestCase):
    """Exercise the real shell import-check function and its exit status."""

    def test_import_failures_fail_the_pipeline_stage(self):
        """A failed Python process or missing success marker cannot pass."""
        script = Path('localPipeline.sh').read_text(encoding='utf-8')
        function = script[script.index('verify_package_import() {'):script.index('\nmain() {')]
        for executable in ('/bin/false', '/bin/true'):
            with self.subTest(executable=executable):
                result = subprocess.run(
                    ['bash', '-c', 'log() { :; }\nROOT_DIR="$PWD"\n'
                     f'PYTHON={executable}\n' + function + '\nverify_package_import'],
                    capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(result.returncode, 0)


class XmlPositionTests(unittest.TestCase):
    """Formatting and commented examples must not change XML element identity."""

    def test_compact_xml_and_comments_update_only_real_translation(self):
        """Exercise both inline elements and misleading elements inside comments."""
        samples = [
            '<TS language="de"><message><source>Hello</source>'
            '<translation type="unfinished"/></message></TS>',
            '<TS language="de"><!-- <message><source>fake</source></message> -->'
            '<message>\n<source>Hello</source>\n<!-- old example:\n'
            '<translation type="unfinished">old</translation>\n-->\n'
            '<translation type="unfinished"/>\n</message></TS>',
            '<TS language="de"><message id="a>b">\n'
            '<source><![CDATA[Hello <message>]]></source>\n'
            '<translation type="unfinished"/>\n</message></TS>',
        ]
        for content in samples:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'app_de.ts'
                path.write_text(content, encoding='utf-8')
                with patch('auto_trans.translate_string', return_value='Grüße') as translator:
                    auto_trans.transform_ts_file(path, 'en', 'de')
                result = path.read_text(encoding='utf-8')
                self.assertIn('<translation>Grüße</translation>', result)
                self.assertEqual(translator.call_count, 1)
                if 'old example' in content:
                    self.assertIn('<translation type="unfinished">old</translation>', result)
                    self.assertIn('<!-- <message><source>fake</source></message> -->', result)


class PluralSlotTests(unittest.TestCase):
    """All existing plural slots survive regardless of empty-element spelling."""

    def test_self_closing_and_mixed_plural_slots_are_filled(self):
        """Check compact self-closing forms and a mixture of paired forms."""
        for forms in ('<numerusform/><numerusform/>',
                      '<numerusform/><numerusform></numerusform><numerusform />'):
            with self.subTest(forms=forms):
                message = '<message numerus="yes"><source>%n files</source>'
                message += f'<translation type="unfinished">{forms}</translation></message>'
                output = auto_trans.replace_translation_in_message(message, '%n Dateien', True)
                self.assertEqual(output.count('<numerusform>%n Dateien</numerusform>'),
                                 forms.count('<numerusform'))
                self.assertNotIn('unfinished', output)


class SourceContentTests(unittest.TestCase):
    """Qt byte elements and source-less messages need schema-aware handling."""

    def test_byte_values_and_tails_reach_translator_and_round_trip(self):
        """Translate the complete logical string, including embedded controls."""
        content = TS_SAMPLE.replace('Hello', 'First<byte value="x9"/>Last<byte value="1"/>!')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app_de.ts'
            path.write_text(content, encoding='utf-8')
            with patch(
                'auto_trans.translate_string', side_effect=lambda text, *_: text
            ) as translator:
                auto_trans.transform_ts_file(path, 'en', 'de')
            translator.assert_called_once_with('First\tLast\x01!', 'en', 'de')
            self.assertIn('<byte value="x1"/>', path.read_text(encoding='utf-8'))
            auto_trans.PositionedXml(path.read_text(encoding='utf-8'))

    def test_missing_and_empty_sources_are_skipped(self):
        """A source-less ID message must not abort other catalog processing."""
        for source in ('', '<source/>', '<source> </source>'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'app_de.ts'
                content = TS_SAMPLE.replace('<source>Hello</source>', source)
                path.write_text(content, encoding='utf-8')
                with patch('auto_trans.translate_string') as translator:
                    summary = auto_trans.transform_ts_file(path, 'en', 'de')
                translator.assert_not_called()
                self.assertEqual(summary['unfinished_before'], 1)
                self.assertEqual(summary['skipped_count'], 1)
                self.assertEqual(summary['translated_count'], 0)
                self.assertEqual(path.read_text(encoding='utf-8'), content)


class LengthVariantTests(unittest.TestCase):
    """Unsupported length variants must be rejected without losing content."""

    def test_length_variants_are_rejected_before_translation(self):
        """Both singular and plural variants leave the source file untouched."""
        for translation in (
            '<translation type="unfinished" variants="yes">'
            '<lengthvariant>Hello</lengthvariant><lengthvariant>Hi</lengthvariant></translation>',
            '<translation type="unfinished"><numerusform variants="yes">'
            '<lengthvariant>%n files</lengthvariant></numerusform></translation>',
        ):
            with self.subTest(translation=translation), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'app_de.ts'
                content = TS_SAMPLE.replace('<translation type="unfinished"/>', translation)
                path.write_text(content, encoding='utf-8')
                with patch('auto_trans.translate_string', return_value='Hallo') as translator:
                    with self.assertRaisesRegex(ValueError, 'Length variants'):
                        auto_trans.transform_ts_file(path, 'en', 'de')
                    translator.assert_not_called()
                self.assertEqual(path.read_text(encoding='utf-8'), content)


class UnfinishedAttributeTests(unittest.TestCase):
    """XML attribute syntax must not leave completed messages unfinished."""

    def test_attribute_quotes_spacing_and_entities_are_supported(self):
        """Only the type attribute is removed; other attribute values survive."""
        for attributes in (" type='unfinished'", ' type = "unfinished"',
                           " type='unf&#105;nished'", " type = 'unfinished' variants='no'"):
            with self.subTest(attributes=attributes):
                message = '<message><source>Hello</source>'
                message += f'<translation{attributes}/></message>'
                output = auto_trans.replace_translation_in_message(message, 'Hallo', False)
                parsed = auto_trans.PositionedXml(output).root.find('translation').element
                self.assertNotIn('type', parsed.attrib)
                self.assertEqual(parsed.text, 'Hallo')
        attributes = ' type="unfinished" custom=" text type=\'unfinished\'  here "'
        self.assertEqual(auto_trans.remove_unfinished_type(attributes),
                         ' custom=" text type=\'unfinished\'  here "')


class FilenameLanguageTests(unittest.TestCase):
    """Project prefixes are not automatically source-language declarations."""

    def test_unknown_prefix_falls_back_to_auto_source(self):
        """A Qt-prefixed catalog uses its target suffix and automatic detection."""
        self.assertEqual(auto_trans.infer_languages_from_filename('qt_de.ts'), (None, 'de'))
        self.assertEqual(auto_trans.infer_languages_from_filename('app_en_de.ts'), ('en', 'de'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'qt_de.ts'
            path.write_text('<TS/>', encoding='utf-8')
            self.assertEqual(auto_trans.resolve_languages(path), ('auto', 'de'))
