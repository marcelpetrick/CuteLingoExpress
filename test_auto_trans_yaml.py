"""Tests for optional LVGL YAML translation support."""

import builtins
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ruamel.yaml.scalarstring import DoubleQuotedScalarString

import auto_trans_yaml


class YamlTranslationTests(unittest.TestCase):
    """Verify round-trip YAML handling and optional dependency behavior."""

    def test_create_yaml_parser_preserves_quotes(self):
        """The configured parser must retain scalar quote styles."""
        yaml = auto_trans_yaml.create_yaml_parser()

        self.assertTrue(yaml.preserve_quotes)

    def test_create_yaml_parser_explains_missing_optional_dependency(self):
        """Missing ruamel.yaml should produce an actionable installation hint."""
        real_import = builtins.__import__

        def import_without_ruamel(name, *args, **kwargs):
            if name == 'ruamel.yaml':
                error = ModuleNotFoundError("No module named 'ruamel'")
                error.name = 'ruamel'
                raise error
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=import_without_ruamel):
            with self.assertRaisesRegex(
                RuntimeError,
                r"pip install 'cutelingoexpress\[yaml\]'",
            ):
                auto_trans_yaml.create_yaml_parser()

    def test_create_yaml_parser_does_not_hide_unrelated_import_errors(self):
        """Only errors for the optional parser dependency should be rewritten."""
        real_import = builtins.__import__

        def import_with_unrelated_failure(name, *args, **kwargs):
            if name == 'ruamel.yaml':
                error = ModuleNotFoundError("No module named 'unexpected_dependency'")
                error.name = 'unexpected_dependency'
                raise error
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=import_with_unrelated_failure):
            with self.assertRaisesRegex(ModuleNotFoundError, 'unexpected_dependency'):
                auto_trans_yaml.create_yaml_parser()

    def test_translate_yaml_node_translates_values_only(self):
        """Nested strings are translated while keys and typed values survive."""
        translator = MagicMock(side_effect=lambda text, source, target: f"{target}:{text}")
        node = {
            'Menu title': DoubleQuotedScalarString('Settings'),
            'items': ['Input', '', 42, True, None, {'nested key': 'Brightness'}],
        }

        translated = auto_trans_yaml.translate_yaml_node(node, 'en', 'de', translator)

        self.assertIs(translated, node)
        self.assertEqual(list(translated), ['Menu title', 'items'])
        self.assertIsInstance(translated['Menu title'], DoubleQuotedScalarString)
        self.assertEqual(translated['Menu title'], 'de:Settings')
        self.assertEqual(
            translated['items'],
            ['de:Input', '', 42, True, None, {'nested key': 'de:Brightness'}],
        )
        self.assertEqual(translator.call_count, 3)

    def test_preserve_scalar_style_copies_anchor(self):
        """Anchored styled scalars retain both style and anchor metadata."""
        original = DoubleQuotedScalarString('Settings')
        original.yaml_set_anchor('settings_label', always_dump=True)

        translated = auto_trans_yaml.preserve_scalar_style(original, 'Einstellungen')

        self.assertIsInstance(translated, DoubleQuotedScalarString)
        self.assertEqual(translated, 'Einstellungen')
        self.assertEqual(translated.anchor.value, 'settings_label')
        self.assertTrue(translated.anchor.always_dump)

    def test_translate_yaml_node_preserves_scalar_alias_identity(self):
        """Aliases should still reference one translated anchored scalar."""
        yaml = auto_trans_yaml.create_yaml_parser()
        node = yaml.load('label: &common "Settings"\nagain: *common\n')
        translator = MagicMock(return_value='Einstellungen')

        translated = auto_trans_yaml.translate_yaml_node(node, 'en', 'de', translator)

        self.assertIs(translated['label'], translated['again'])
        self.assertEqual(translator.call_count, 1)

        with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as output_file:
            yaml.dump(translated, output_file)
            output_file.seek(0)
            output_content = output_file.read()
        self.assertEqual(output_content.count('&common'), 1)
        self.assertEqual(output_content.count('*common'), 1)

    def test_preserve_scalar_style_returns_plain_string(self):
        """Ordinary Python strings should remain ordinary strings."""
        self.assertEqual(
            auto_trans_yaml.preserve_scalar_style('Settings', 'Einstellungen'),
            'Einstellungen',
        )

    def test_build_output_path_supports_yaml_and_yml(self):
        """Output paths should be siblings with a target-language suffix."""
        self.assertEqual(
            auto_trans_yaml.build_output_path(Path('/tmp/osd_en.yaml'), 'de'),
            Path('/tmp/osd_en_de.yaml'),
        )
        self.assertEqual(
            auto_trans_yaml.build_output_path(Path('/tmp/osd.yml'), 'zh-CN'),
            Path('/tmp/osd_zh-CN.yml'),
        )

    def test_build_output_path_rejects_invalid_inputs(self):
        """Non-YAML inputs and path-like target values must fail clearly."""
        with self.assertRaisesRegex(ValueError, r"requires a \.yaml or \.yml"):
            auto_trans_yaml.build_output_path('osd.json', 'de')
        for target in ('', '../de', r'..\de'):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, 'non-empty language code'):
                    auto_trans_yaml.build_output_path('osd.yaml', target)

    def test_translate_yaml_file_preserves_lvgl_formatting(self):
        """Comments, keys, quotes, blocks, collections, and source input survive."""
        content = """# LVGL translation file
menu: # section comment
  title: "Settings"
  subtitle: 'Display options'
  description: |
    First line
    Second line
  choices:
    - "Input"
    - 42
    - true
"""
        translator = MagicMock(side_effect=lambda text, _source, _target: f"X:{text}")

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / 'osd_en.yaml'
            source_path.write_text(content, encoding='utf-8')

            output_path = auto_trans_yaml.translate_yaml_file(
                source_path,
                'en',
                'de',
                translator,
            )
            source_content = source_path.read_text(encoding='utf-8')
            output_content = output_path.read_text(encoding='utf-8')
            parsed_output = auto_trans_yaml.create_yaml_parser().load(output_content)

        self.assertEqual(source_content, content)
        self.assertEqual(output_path.name, 'osd_en_de.yaml')
        self.assertIn('# LVGL translation file', output_content)
        self.assertIn('# section comment', output_content)
        self.assertIn('title: "X:Settings"', output_content)
        self.assertIn("subtitle: 'X:Display options'", output_content)
        self.assertIn('description: |', output_content)
        self.assertEqual(
            list(parsed_output['menu']),
            ['title', 'subtitle', 'description', 'choices'],
        )
        self.assertEqual(parsed_output['menu']['choices'], ['X:Input', 42, True])
        self.assertEqual(translator.call_count, 4)

    def test_real_lvgl_fixture_round_trips_without_key_or_comment_loss(self):
        """The PR's full LVGL template remains structurally valid after translation."""
        fixture_path = Path('testing/lvgl/Template-en_US.yaml')
        translator = MagicMock(side_effect=lambda text, _source, _target: f"DE:{text}")
        yaml = auto_trans_yaml.create_yaml_parser()

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / fixture_path.name
            shutil.copyfile(fixture_path, source_path)
            original_data = yaml.load(source_path.read_text(encoding='utf-8'))

            output_path = auto_trans_yaml.translate_yaml_file(
                source_path,
                'en',
                'de',
                translator,
            )
            output_content = output_path.read_text(encoding='utf-8')
            translated_data = yaml.load(output_content)

        self.assertEqual(list(translated_data), list(original_data))
        self.assertEqual(
            list(translated_data['OSD Status Information']),
            list(original_data['OSD Status Information']),
        )
        self.assertEqual(
            translated_data['OSD Status Information']['Information'],
            'DE:Information',
        )
        self.assertIn("# items below belong to 'Gamma' sub-menu", output_content)
        self.assertGreater(translator.call_count, 100)

    def test_translate_yaml_file_preserves_comment_only_input(self):
        """A YAML file without data must not be rewritten as a null document."""
        content = '# LVGL translation placeholder\n\n'
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / 'empty_en.yaml'
            source_path.write_text(content, encoding='utf-8')

            output_path = auto_trans_yaml.translate_yaml_file(
                source_path,
                'en',
                'de',
                MagicMock(),
            )
            output_content = output_path.read_text(encoding='utf-8')

        self.assertEqual(output_content, content)

    @patch('auto_trans_yaml.Path.replace', side_effect=OSError('disk full'))
    def test_translate_yaml_file_removes_temporary_file_after_failure(
        self,
        _mock_replace,
    ):
        """A failed final replace must not leave a temporary YAML file behind."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / 'osd_en.yaml'
            source_path.write_text('title: "Settings"\n', encoding='utf-8')

            with self.assertRaisesRegex(OSError, 'disk full'):
                auto_trans_yaml.translate_yaml_file(
                    source_path,
                    'en',
                    'de',
                    lambda text, _source, _target: text,
                )

            temporary_files = list(Path(temp_dir).glob('*.tmp'))

        self.assertEqual(temporary_files, [])


if __name__ == '__main__':
    unittest.main()
