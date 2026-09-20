"""
Optional translation support for LVGL-style YAML files.

The module is loaded only for ``--lvgl-yaml`` invocations so the core Qt TS
workflow does not require a YAML parser.
"""

from collections.abc import Mapping, MutableMapping, MutableSequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile

from auto_trans import translate_string


OPTIONAL_DEPENDENCY_MESSAGE = (
    "LVGL YAML support requires the optional YAML dependency. "
    "Install it with: python -m pip install 'cutelingoexpress[yaml]'"
)


def create_yaml_parser():
    """Create the round-trip YAML parser or explain how to enable the feature."""
    try:
        from ruamel.yaml import YAML  # pylint: disable=import-outside-toplevel
    except ModuleNotFoundError as error:
        if error.name == 'ruamel' or error.name.startswith('ruamel.'):
            raise RuntimeError(OPTIONAL_DEPENDENCY_MESSAGE) from error
        raise

    yaml = YAML()
    yaml.preserve_quotes = True
    return yaml


def preserve_scalar_style(original, translated_text):
    """Return translated text using the original YAML scalar class and anchor."""
    if not hasattr(original, 'yaml_set_anchor'):
        return translated_text

    translated = type(original)(translated_text)
    anchor = getattr(original, 'anchor', None)
    if anchor is not None and anchor.value is not None:
        translated.yaml_set_anchor(anchor.value, always_dump=anchor.always_dump)
    return translated


@dataclass
class TranslationContext:
    """Track aliases, immutable keys, and already reserved anchor names."""

    translated: dict = field(default_factory=dict)
    key_ids: set = field(default_factory=set)
    anchors: set = field(default_factory=set)

    def inspect(self, node, visited=None):
        """Collect anchor names and key identities before changing any values."""
        visited = set() if visited is None else visited
        if id(node) in visited:
            return
        visited.add(id(node))
        anchor = getattr(node, 'anchor', None)
        if anchor is not None and anchor.value:
            self.anchors.add(anchor.value)
        if isinstance(node, Mapping):
            for key, value in node.items():
                self.key_ids.add(id(key))
                self.inspect(key, visited)
                self.inspect(value, visited)
            for merged in getattr(node, 'merge', ()):
                self.inspect(merged, visited)
        elif isinstance(node, MutableSequence):
            for value in node:
                self.inspect(value, visited)

    def split_key_anchor(self, original, translated):
        """Keep the key unchanged and give translated aliases a fresh anchor."""
        if id(original) not in self.key_ids or not hasattr(original, 'yaml_set_anchor'):
            return translated
        if original == translated:
            return original
        anchor = getattr(original, 'anchor', None)
        if anchor is not None and anchor.value:
            base = f'{anchor.value}_translated'
            candidate = base
            suffix = 1
            while candidate in self.anchors:
                candidate = f'{base}_{suffix}'
                suffix += 1
            self.anchors.add(candidate)
            translated.yaml_set_anchor(candidate, always_dump=True)
        return translated


def translate_yaml_node(node, source_language, target_language, translator=translate_string):
    """Translate values while retaining YAML aliases and immutable mapping keys."""
    context = TranslationContext()
    context.inspect(node)
    return _translate_yaml_node(node, source_language, target_language, translator, context)


def _translate_yaml_node(
    node,
    source_language,
    target_language,
    translator,
    context,
):
    """Recursively translate YAML string values while leaving keys unchanged."""
    translated_nodes = context.translated

    node_id = id(node)
    if node_id in translated_nodes:
        return translated_nodes[node_id]

    if isinstance(node, str):
        if not node.strip():
            return node
        translated_text = translator(node, source_language, target_language)
        translated_node = context.split_key_anchor(
            node, preserve_scalar_style(node, translated_text),
        )
        translated_nodes[node_id] = translated_node
        return translated_node

    if isinstance(node, MutableSequence):
        translated_nodes[node_id] = node
        for index, item in enumerate(node):
            node[index] = _translate_yaml_node(
                item,
                source_language,
                target_language,
                translator,
                context,
            )
        return node

    if isinstance(node, MutableMapping):
        translated_nodes[node_id] = node
        for merged in getattr(node, 'merge', ()):
            _translate_yaml_node(
                merged, source_language, target_language, translator, context,
            )
        items = node.non_merged_items() if hasattr(node, 'non_merged_items') else node.items()
        for key, value in items:
            node[key] = _translate_yaml_node(
                value,
                source_language,
                target_language,
                translator,
                context,
            )
        return node

    return node


def build_output_path(input_path, target_language):
    """Build a sibling output filename carrying the requested target language."""
    path = Path(input_path)
    if path.suffix.lower() not in {'.yaml', '.yml'}:
        raise ValueError("LVGL YAML mode requires a .yaml or .yml input file.")
    if not target_language or any(separator in target_language for separator in ('/', '\\')):
        raise ValueError("Target language must be a non-empty language code.")
    return path.with_name(f"{path.stem}_{target_language}{path.suffix}")


def translate_yaml_file(
    input_path,
    source_language,
    target_language,
    translator=translate_string,
):
    """Translate an LVGL YAML file to a separate, atomically written output file."""
    yaml = create_yaml_parser()
    source_path = Path(input_path)
    output_path = build_output_path(source_path, target_language)

    source_content = source_path.read_text(encoding='utf-8')
    data = yaml.load(source_content)

    translated_data = translate_yaml_node(
        data,
        source_language,
        target_language,
        translator,
    )

    temporary_path = None
    try:
        with NamedTemporaryFile(
            'w',
            encoding='utf-8',
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix='.tmp',
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            if translated_data is None:
                temporary_file.write(source_content)
            else:
                yaml.dump(translated_data, temporary_file)
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return output_path
