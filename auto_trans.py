"""
This is a Python script for translating .ts files from one language to another.
It makes use of the translators library to translate individual strings in the file,
updating the file with the new translations.
"""

import sys
import re
import time
import xml.etree.ElementTree
from contextlib import contextmanager
from xml.sax.saxutils import escape

from cutelingoexpress_version import VERSION, get_startup_banner


__version__ = VERSION

MESSAGE_PATTERN = re.compile(r'(<message\b[^>]*>.*?</message>)', re.DOTALL)
SOURCE_PATTERN = re.compile(r'<source>(.*?)</source>', re.DOTALL)
TRANSLATION_PATTERN = re.compile(
    r'(?P<indent>^[ \t]*)<translation\b(?P<attrs>[^>]*?)(?P<self_closing>\s*/>|>(?P<inner>.*?)</translation>)',
    re.DOTALL | re.MULTILINE,
)


@contextmanager
def preserve_xml_text_entities():
    """
    Temporarily configure ElementTree to serialize quote characters in text
    nodes as XML entities so Qt TS files keep their original escaping style.
    """
    original_escape_cdata = xml.etree.ElementTree._escape_cdata

    def escape_cdata_with_entities(text):
        return (
            original_escape_cdata(text)
            .replace('"', '&quot;')
            .replace("'", '&apos;')
        )

    xml.etree.ElementTree._escape_cdata = escape_cdata_with_entities
    try:
        yield
    finally:
        xml.etree.ElementTree._escape_cdata = original_escape_cdata


def write_ts_tree(tree, ts_file_path):
    """
    Write a Qt TS file while preserving quote entities in text content to avoid
    noisy diffs.
    """
    with preserve_xml_text_entities():
        tree.write(ts_file_path, encoding='utf-8', xml_declaration=True)


def escape_ts_text(text, preserve_double_quotes=False, preserve_single_quotes=False):
    """
    Escape translated TS text while optionally matching the entity style seen in
    the original source string.
    """
    entity_map = {}
    if preserve_double_quotes:
        entity_map['"'] = '&quot;'
    if preserve_single_quotes:
        entity_map["'"] = '&apos;'
    return escape(text, entity_map)


def remove_unfinished_type(attributes_text):
    """
    Remove the ``type="unfinished"`` attribute while preserving any other
    translation attributes.
    """
    updated_attributes = re.sub(r'\s+type="unfinished"', '', attributes_text)
    updated_attributes = re.sub(r'\s+', ' ', updated_attributes).strip()
    return f' {updated_attributes}' if updated_attributes else ''


def replace_translation_in_message(message_block, translated_text, numerus):
    """
    Replace the unfinished translation inside a single message block while
    leaving all unrelated XML untouched.
    """
    source_match = SOURCE_PATTERN.search(message_block)
    translation_match = TRANSLATION_PATTERN.search(message_block)
    if source_match is None or translation_match is None:
        raise ValueError("Unable to locate source or translation block in TS message.")

    source_raw = source_match.group(1)
    translation_indent = translation_match.group('indent')
    updated_attributes = remove_unfinished_type(translation_match.group('attrs'))
    inner_content = translation_match.group('inner') or ""

    escaped_translation = escape_ts_text(
        translated_text,
        preserve_double_quotes='&quot;' in source_raw,
        preserve_single_quotes='&apos;' in source_raw,
    )

    if numerus:
        numerusform_indent_match = re.search(
            r'^[ \t]*(?=<numerusform>)',
            inner_content,
            re.MULTILINE,
        )
        numerusform_indent = (
            numerusform_indent_match.group(0)
            if numerusform_indent_match is not None
            else f"{translation_indent}    "
        )
        replacement = (
            f"{translation_indent}<translation{updated_attributes}>\n"
            f"{numerusform_indent}<numerusform>{escaped_translation}</numerusform>\n"
            f"{numerusform_indent}<numerusform>{escaped_translation}</numerusform>\n"
            f"{translation_indent}</translation>"
        )
    else:
        replacement = (
            f"{translation_indent}<translation{updated_attributes}>"
            f"{escaped_translation}</translation>"
        )

    return (
        message_block[:translation_match.start()]
        + replacement
        + message_block[translation_match.end():]
    )


def update_ts_content(original_content, translated_messages):
    """
    Apply translation updates to the original TS file content without
    reserializing untouched XML.
    """
    updated_parts = []
    last_index = 0
    message_matches = list(MESSAGE_PATTERN.finditer(original_content))

    if len(message_matches) != len(translated_messages):
        raise ValueError("TS message count changed while processing the file.")

    for message_match, message_update in zip(message_matches, translated_messages):
        updated_parts.append(original_content[last_index:message_match.start()])
        message_block = message_match.group(1)

        if message_update is None:
            updated_parts.append(message_block)
        else:
            updated_parts.append(
                replace_translation_in_message(
                    message_block,
                    message_update['translated_text'],
                    message_update['numerus'],
                )
            )

        last_index = message_match.end()

    updated_parts.append(original_content[last_index:])
    updated_content = ''.join(updated_parts)
    return updated_content if updated_content.endswith('\n') else f"{updated_content}\n"


def get_help_text() -> str:
    """
    Return a concise help message for the command line interface.
    """
    return (
        "Translate unfinished entries in a Qt .ts file in place.\n"
        "\n"
        "Usage: python auto_trans.py <ts_file_path> <source_language> <target_language>\n"
        "\n"
        "Examples:\n"
        "  python auto_trans.py testing/helloworld.ts en cn\n"
        "  python auto_trans.py --help\n"
    )


def replace_first_lines(file_path):
    """
    Replaces the first two lines of a file with the XML declaration and DOCTYPE.

    :param file_path: The path to the file to modify.
    :type file_path: str
    """
    with open(file_path, 'r+', encoding='utf-8') as file:
        lines = file.readlines()
        lines[0] = '<?xml version="1.0" encoding="utf-8"?>\n'
        lines.insert(1, '<!DOCTYPE TS>\n')

        file.seek(0)
        file.writelines(lines)
        file.truncate()


def translate_string(source_string: str, source_language: str, target_language: str) -> str:
    """
    ...

    :param source_string: The string to translate.
    :type source_string: str
    :param source_language: The ISO 639-1 code of the language to translate from.
    :type source_language: str
    :param target_language: The ISO 639-1 code of the language to translate to.
    :type target_language: str
    :return: The translated string.
    :rtype: str
    """
    import translators

    start_time = time.time()
    output = translators.google(source_string, source_language, target_language)
    print(
        f"translateString: {time.time() - start_time}s : {source_string} -> {output} "
        f"({source_language} -> {target_language})"
    )

    return output


def transform_ts_file(ts_file_path, _language, target_language):
    """
    Transforms a .ts file by translating all 'unfinished' messages.
    The translated messages replace the original messages in the .ts file.

    :param ts_file_path: The path to the .ts file to transform.
    :type ts_file_path: str
    :param _language: The ISO 639-1 code of the source language.
    :type _language: str
    :param target_language: The ISO 639-1 code of the target language.
    :type target_language: str
    """
    with open(ts_file_path, 'r', encoding='utf-8') as file:
        original_content = file.read()

    tree = xml.etree.ElementTree.parse(ts_file_path)
    root = tree.getroot()
    translated_messages = []

    for message in root.iter('message'):
        numerus = message.attrib.get('numerus') == 'yes'
        if numerus:
            source_text = message.find('source').text
            unfinished_translation = message.find('translation')
            if unfinished_translation is not None and \
                    unfinished_translation.attrib.get('type') == 'unfinished':
                translated_text = translate_string(source_text, _language, target_language)
                translated_messages.append({
                    'translated_text': translated_text,
                    'numerus': True,
                })
            else:
                translated_messages.append(None)
        else:
            translation = message.find('translation')
            if translation is not None and translation.attrib.get('type') == 'unfinished':
                source_text = message.find('source').text
                translated_text = translate_string(source_text, _language, target_language)
                translated_messages.append({
                    'translated_text': translated_text,
                    'numerus': False,
                })
            else:
                translated_messages.append(None)

    updated_content = update_ts_content(original_content, translated_messages)
    with open(ts_file_path, 'w', encoding='utf-8') as file:
        file.write(updated_content)

    print("TS file transformed successfully.")


def main():
    """
    The main entry point of the script. It checks if a file path was given as
    command line argument and if so, calls the function to transform the .ts file.
    """
    print(get_startup_banner())

    if len(sys.argv) == 2 and sys.argv[1] in {"--version", "-V"}:
        return

    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] in {"--help", "-h"}):
        print(get_help_text())
        return

    if len(sys.argv) < 4:
        print(get_help_text())
        return

    ts_file_path = sys.argv[1]
    start_time = time.time()
    transform_ts_file(ts_file_path, sys.argv[2], sys.argv[3])
    print(f"Whole execution took {time.time() - start_time}s.")


if __name__ == "__main__":
    main()

# test call:
# python auto_trans.py testing/helloworld.ts en cn
#
# Using Germany server backend.
# translateString: 1.3896245956420898s : Hello world! -> 你好世界！ (en -> cn)
# translateString: 1.9492523670196533s : My first dish. -> 我的第一道菜。 (en -> cn)
# translateString: 2.112003803253174s : white bread with butter -> 白面包和黄油 (en -> cn)
# TS file transformed successfully.
# Whole execution took 5.453961610794067s.
# (venv) [mpetrick@marcel-precision3551 AutoTrans]$

# manual tests:
# python auto_trans.py testing/numerus.ts de cn
# python auto_trans.py testing/helloworld.ts en cn
