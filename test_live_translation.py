"""Opt-in installed-command tests against real translation services and fixtures.

Run after ./localPipeline.sh with CUTELINGOEXPRESS_LIVE_TESTS=1.
Fixture copies are disposable; CLI logs remain in CUTELINGOEXPRESS_LIVE_OUTPUT.
"""

from collections import Counter
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from auto_trans_yaml import create_yaml_parser


ROOT = Path(__file__).resolve().parent
LIVE_OUTPUT = Path(os.environ.get('CUTELINGOEXPRESS_LIVE_OUTPUT', '/tmp/cle-live-validation'))
COMMAND = Path(os.environ.get('CUTELINGOEXPRESS_COMMAND', ROOT / '.venv/bin/cutelingoexpress'))
PLACEHOLDERS = re.compile(r'%(?:L?[1-9][0-9]?|L?n)')


@unittest.skipUnless(os.environ.get('CUTELINGOEXPRESS_LIVE_TESTS') == '1',
                     'Set CUTELINGOEXPRESS_LIVE_TESTS=1 to contact real translation services')
class LiveTranslationTests(unittest.TestCase):
    """Validate installed CLI behavior and full-file structural invariants."""

    def run_cli(self, directory, name, *arguments):
        """Use the installed entrypoint from outside the source tree."""
        LIVE_OUTPUT.mkdir(parents=True, exist_ok=True)
        log_path = LIVE_OUTPUT / f'{name}.log'
        with log_path.open('w', encoding='utf-8') as output:
            result = subprocess.run(
                [str(COMMAND), *map(str, arguments)], cwd=directory,
                stdout=output, stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}, timeout=1800, check=False,
            )
        log = log_path.read_text(encoding='utf-8')
        self.assertEqual(result.returncode, 0, log[-6000:])
        self.assertIn('translateString[', log)
        return log

    def check_ts_fixture(self, filename):
        """Preserve every source, completed entry, placeholder, and plural slot."""
        fixture = ROOT / 'testing' / filename
        original = fixture.read_bytes()
        before = ET.fromstring(original)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / filename
            shutil.copyfile(fixture, path)
            self.run_cli(directory, filename, path, 'en', 'de')
            after = ET.parse(path).getroot()
            self.check_qt_compilation(path)
        self.assertEqual(fixture.read_bytes(), original)
        self.assertEqual(before.attrib, after.attrib)
        old_messages = list(before.iter('message'))
        new_messages = list(after.iter('message'))
        self.assertEqual(len(old_messages), len(new_messages))
        for old, new in zip(old_messages, new_messages):
            self.assert_ts_message(old, new)

    def check_qt_compilation(self, path):
        """Compile the translated catalog when Qt Linguist tools are installed."""
        compiler = shutil.which('lrelease6') or shutil.which('lrelease')
        if compiler is not None:
            output = path.with_suffix('.qm')
            result = subprocess.run([compiler, str(path), '-qm', str(output)],
                                    capture_output=True, text=True, check=False)
            (LIVE_OUTPUT / f'{path.name}.qt.log').write_text(
                result.stdout + result.stderr, encoding='utf-8',
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertGreater(output.stat().st_size, 0)

    def assert_ts_message(self, old, new):
        """Check the source, translated content, and placeholders of one message."""
        self.assertEqual(ET.tostring(old.find('source')), ET.tostring(new.find('source')))
        previous = old.find('translation')
        translated = new.find('translation')
        if previous is None:
            self.assertIsNone(translated)
        elif previous.get('type') != 'unfinished':
            self.assertEqual(ET.tostring(previous), ET.tostring(translated))
        else:
            self.assertIsNotNone(translated)
            self.assertNotEqual(translated.get('type'), 'unfinished')
            forms = translated.findall('numerusform')
            self.assertEqual(len(forms), len(previous.findall('numerusform')))
            source = ''.join(old.find('source').itertext())
            for value in forms or [translated]:
                text = ''.join(value.itertext())
                self.assertTrue(text.strip())
                self.assertEqual(Counter(PLACEHOLDERS.findall(source)),
                                 Counter(PLACEHOLDERS.findall(text)), text)

    def test_keepassxc_catalog(self):
        """Translate the full real KeePassXC catalog's unfinished entries."""
        self.check_ts_fixture('keepassxc_de.ts')

    def test_hello_world_catalog(self):
        """Translate a mixed catalog with completed entries and plural forms."""
        self.check_ts_fixture('helloworld.ts')

    def test_plural_catalog(self):
        """Translate the standalone numerus fixture without losing its slots."""
        self.check_ts_fixture('numerus.ts')

    def assert_yaml_shape(self, before, after):
        """Check keys, ordering, types, and non-string values recursively."""
        if isinstance(before, dict):
            self.assertEqual(list(before), list(after))
            for key, value in before.items():
                self.assert_yaml_shape(value, after[key])
        elif isinstance(before, list):
            self.assertEqual(len(before), len(after))
            for old, new in zip(before, after):
                self.assert_yaml_shape(old, new)
        elif isinstance(before, str):
            self.assertIsInstance(after, str)
            self.assertEqual(type(before), type(after))
            if before.strip():
                self.assertTrue(after.strip())
        else:
            self.assertEqual(before, after)
            self.assertIs(type(before), type(after))

    def test_full_lvgl_template(self):
        """Translate all LVGL values and preserve keys, styles, and comments."""
        fixture = ROOT / 'testing/lvgl/Template-en_US.yaml'
        original = fixture.read_bytes()
        parser = create_yaml_parser()
        before = parser.load(original.decode('utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / fixture.name
            shutil.copyfile(fixture, path)
            self.run_cli(directory, 'lvgl', '--lvgl-yaml', path, 'en', 'de')
            self.assertEqual(path.read_bytes(), original)
            output = path.with_name(f'{path.stem}_de.yaml').read_text(encoding='utf-8')
            after = parser.load(output)
        self.assertEqual(fixture.read_bytes(), original)
        self.assert_yaml_shape(before, after)
        self.assertNotEqual(before, after)
        for line in original.decode('utf-8').splitlines():
            if line.lstrip().startswith('#'):
                self.assertIn(line.strip(), output)
