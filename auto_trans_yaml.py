"""
Translate all string values in a YAML file while preserving comments and structure.
Requires: ruamel.yaml
"""

import sys
import time
from ruamel.yaml import YAML
import translators


def translate_string(text: str, source_lang: str, target_lang: str) -> str:
    """Translate a single string value."""
    if not isinstance(text, str) or not text.strip():
        return text

    start_time = time.time()
    result = translators.translate_text(
        text,
        translator="google",
        from_language=source_lang,
        to_language=target_lang
    )
    print(f"translateString: {time.time() - start_time:.3f}s : {text} -> {result}")
    return result


def translate_node(node, source_lang, target_lang):
    """Recursively translate YAML nodes while preserving comments."""
    from ruamel.yaml.scalarstring import (
        SingleQuotedScalarString,
        DoubleQuotedScalarString,
        PlainScalarString,
    )

    # Translate scalars
    if isinstance(node, str):
        translated = translate_string(node, source_lang, target_lang)
        # preserve style
        if isinstance(node, SingleQuotedScalarString):
            return SingleQuotedScalarString(translated)
        elif isinstance(node, DoubleQuotedScalarString):
            return DoubleQuotedScalarString(translated)
        elif isinstance(node, PlainScalarString):
            return PlainScalarString(translated)
        return translated

    # Process lists
    if isinstance(node, list):
        for i in range(len(node)):
            node[i] = translate_node(node[i], source_lang, target_lang)
        return node

    # Process dicts
    if isinstance(node, dict):
        for key in node:
            node[key] = translate_node(node[key], source_lang, target_lang)
        return node

    # Keep all other types unchanged
    return node


def translate_yaml_file(path, src_lang, tgt_lang):
    print(f"Loading YAML: {path}")

    yaml = YAML()
    yaml.preserve_quotes = True

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.load(f)

    print("Translating YAML content...")
    translate_node(data, src_lang, tgt_lang)

    output_path = path.replace(".yaml", f"_{tgt_lang}.yaml")

    print(f"Saving translated YAML to {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    print("Translation completed successfully.")


def main():
    if len(sys.argv) < 4:
        print("Usage: python auto_trans_yaml.py <yaml_file> <source_lang> <target_lang>")
        return

    translate_yaml_file(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
