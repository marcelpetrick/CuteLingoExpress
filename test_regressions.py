"""Regression tests for issues found in the repository review."""

import tempfile
import io
import subprocess
import sys
import warnings
import unittest
from pathlib import Path
from unittest.mock import patch

import auto_trans
import auto_trans_yaml


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


class YamlMergeTests(unittest.TestCase):
    """Translations preserve inherited YAML values as actual merge relationships."""

    def test_merged_values_do_not_become_explicit_overrides(self):
        """Round-trip and edit defaults to check inheritance, not just equal values."""
        parser = auto_trans_yaml.create_yaml_parser()
        data = parser.load('defaults: &defaults\n  title: Hello\ncopy:\n  <<: *defaults\n')
        auto_trans_yaml.translate_yaml_node(data, 'en', 'de', lambda text, *_: 'X:' + text)
        output = io.StringIO()
        parser.dump(data, output)
        self.assertEqual(output.getvalue().count('title:'), 1)
        reloaded = parser.load(output.getvalue().replace('X:Hello', 'Changed default'))
        self.assertEqual(reloaded['copy']['title'], 'Changed default')

    def test_inline_merge_sources_are_translated(self):
        """Merge mappings without a separate named entry must also be visited."""
        parser = auto_trans_yaml.create_yaml_parser()
        data = parser.load('copy:\n  <<: {title: Hello}\n  own: World\n')
        auto_trans_yaml.translate_yaml_node(data, 'en', 'de', lambda text, *_: 'X:' + text)
        output = io.StringIO()
        parser.dump(data, output)
        self.assertEqual(output.getvalue().count('title:'), 1)
        self.assertEqual(parser.load(output.getvalue())['copy']['title'], 'X:Hello')


class YamlKeyAnchorTests(unittest.TestCase):
    """Values shared with immutable mapping keys need distinct translated anchors."""

    def test_key_alias_translation_uses_unique_anchor(self):
        """Reload without warnings and retain sharing between translated values."""
        parser = auto_trans_yaml.create_yaml_parser()
        content = '? &label Hello\n: value\nother: *label\nagain: *label\n'
        content += 'reserved: &label_translated Existing\n'
        data = parser.load(content)
        auto_trans_yaml.translate_yaml_node(data, 'en', 'de', lambda text, *_: 'X:' + text)
        output = io.StringIO()
        parser.dump(data, output)
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            parsed = parser.load(output.getvalue())
        self.assertIn('Hello', parsed)
        self.assertEqual(parsed['other'], 'X:Hello')
        self.assertIs(parsed['other'], parsed['again'])
        self.assertEqual(output.getvalue().count('&label '), 1)


class CliExitStatusTests(unittest.TestCase):
    """Automation must distinguish invalid invocations from successful commands."""

    def test_invalid_invocations_exit_with_usage_error(self):
        """Run the actual CLI as a child process, without a translation backend."""
        for arguments in (['--lvgl-yaml', 'missing.yaml'],
                          ['missing.ts', 'en', 'de', 'extra']):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, 'auto_trans.py', *arguments],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn('Usage:', result.stdout)


class ReleaseRetryTests(unittest.TestCase):
    """Run release tag steps against isolated repositories and a local remote."""

    @staticmethod
    def git(repository, *arguments):
        """Execute a checked Git command without touching the working repository."""
        return subprocess.run(['git', '-C', str(repository), *arguments],
                              capture_output=True, text=True, check=True)

    @staticmethod
    def run_step(repository, publish=False):
        """Execute the workflow's actual shell step with test expression values."""
        workflow = auto_trans_yaml.create_yaml_parser().load(
            Path('.github/workflows/release.yml').read_text(encoding='utf-8')
        )
        names = (('Create and push tag',) if publish else
                 ('Fail if tag already exists', 'Verify release tag'))
        step = next(step for step in workflow['jobs']['release']['steps'] if step['name'] in names)
        command = step['run'].replace('${{ steps.version.outputs.tag }}', 'v1.2.3')
        command = command.replace('${{ github.actor }}', 'regression-test')
        return subprocess.run(['bash', '-e', '-c', command], cwd=repository,
                              capture_output=True, text=True, check=False)

    def test_release_retry_accepts_same_commit_and_rejects_different_commit(self):
        """An already-pushed tag is resumable only for its exact commit."""
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / 'work'
            remote = Path(directory) / 'remote.git'
            repository.mkdir()
            remote.mkdir()
            self.git(remote, 'init', '--bare')
            self.git(repository, 'init')
            self.git(repository, 'config', 'user.name', 'Regression Test')
            self.git(repository, 'config', 'user.email', 'test@example.invalid')
            self.git(repository, 'config', 'commit.gpgsign', 'false')
            self.git(repository, 'config', 'tag.gpgsign', 'false')
            self.git(repository, 'remote', 'add', 'origin', str(remote))
            self.git(repository, 'commit', '--allow-empty', '-m', 'test fixture')
            self.assertEqual(self.run_step(repository).returncode, 0)
            self.assertEqual(self.run_step(repository, publish=True).returncode, 0)
            retry = self.run_step(repository)
            self.assertEqual(retry.returncode, 0, retry.stderr + retry.stdout)
            self.assertEqual(self.run_step(repository, publish=True).returncode, 0)
            self.git(repository, 'commit', '--allow-empty', '-m', 'different commit')
            self.assertNotEqual(self.run_step(repository).returncode, 0)


class NewlinePreservationTests(unittest.TestCase):
    """Catalog edits preserve original newlines and avoid no-op replacements."""

    def test_crlf_is_preserved_and_finished_files_are_not_written(self):
        """Test both a translated Windows-format file and an unchanged catalog."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app_de.ts'
            content = TS_SAMPLE.replace('\n', '\r\n').encode('utf-8')
            path.write_bytes(content)
            with patch('auto_trans.translate_string', return_value='Hallo'):
                auto_trans.transform_ts_file(path, 'en', 'de')
            output = path.read_bytes()
            self.assertEqual(output.count(b'\r\n'), content.count(b'\r\n'))
            self.assertNotIn(b'\n', output.replace(b'\r\n', b''))
            # No trailing newline is also meaningful source formatting.
            path.write_bytes(output.rstrip(b'\r\n'))
            before = path.read_bytes()
            with patch('auto_trans.write_ts_content') as writer:
                auto_trans.transform_ts_file(path, 'en', 'de')
                writer.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
