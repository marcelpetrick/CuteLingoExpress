#!/usr/bin/env python3
"""
Translate all string values in a YAML file using translators library.

Usage:
    python yaml_translator.py <yaml_file> <source_lang> <target_lang>

Example:
    python yaml_translator.py Template-en_US.yaml en de
"""

import sys
import time
import yaml
import translators


def translate_string(text: str, source_lang: str, target_lang: str) -> str:
    """Translate a single string."""
    if not isinstance(text, str) or not text.strip():
        return text

    start = time.time()
    result = translators.translate_text(
        text,
        translator="google",
        from_language=source_lang,
        to_language=target_lang
    )
    print(f"translateString: {time.time() - start:.3f}s : {text} -> {result}")
    return result


def translate_node(node, source_lang, target_lang):
    """
    Recursively translate YAML node content:
    - strings → translated
    - lists → each item processed
    - dicts → values processed, keys unchanged
    """
    if isinstance(node, str):
        return translate_string(node, source_lang, target_lang)

    if isinstance(node, list):
        return [translate_node(item, source_lang, target_lang) for item in node]

    if isinstance(node, dict):
        return {key: translate_node(value, source_lang, target_lang) for key, value in node.items()}

    # numbers, booleans, None stay unchanged
    return node


def translate_yaml_file(path, src_lang, tgt_lang):
    """Main YAML translation pipeline."""
    print(f"Loading YAML: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    print("Translating YAML content...")
    translated = translate_node(data, src_lang, tgt_lang)

    output_path = path.replace(".yaml", f"_{tgt_lang}.yaml")

    print(f"Saving translated YAML → {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(translated, f, allow_unicode=True, sort_keys=False)

    print("Translation completed.")


def main():
    if len(sys.argv) < 4:
        print("Usage: python yaml_translator.py <yaml_file> <source_lang> <target_lang>")
        return

    translate_yaml_file(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
