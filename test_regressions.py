"""Regression tests for issues found in the repository review."""

import tempfile
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
