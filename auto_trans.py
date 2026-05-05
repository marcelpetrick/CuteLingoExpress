"""
Translate unfinished entries in Qt `.ts` files.

The script uses the `translators` library to translate individual source
strings and writes the updated translations back to the original file.
"""

import sys
import importlib
import re
import time
import xml.etree.ElementTree
from contextlib import contextmanager
from xml.sax.saxutils import escape

from version import VERSION, get_startup_banner


__version__ = VERSION
PROJECT_URL = "https://github.com/marcelpetrick/CuteLingoExpress"
TRANSLATION_BACKENDS = ("google", "bing", "myMemory")
TRANSLATION_TIMEOUT_SECONDS = 20.0

MESSAGE_PATTERN = re.compile(r'(<message\b[^>]*>.*?</message>)', re.DOTALL)
SOURCE_PATTERN = re.compile(r'<source>(.*?)</source>', re.DOTALL)
TRANSLATION_PATTERN = re.compile(
    (
        r'(?P<indent>^[ \t]*)<translation\b(?P<attrs>[^>]*?)'
        r'(?P<self_closing>\s*/>|>(?P<inner>.*?)</translation>)'
    ),
    re.DOTALL | re.MULTILINE,
)
NUMERUS_FORM_PATTERN = re.compile(
    r'(<numerusform\b[^>]*>)(.*?)(</numerusform>)',
    re.DOTALL,
)


class TranslationBackendError(RuntimeError):
    """
    Raised when all configured translation backends fail for a source string.
    """


@contextmanager
def preserve_xml_text_entities():
    """
    Temporarily configure ElementTree to serialize quote characters in text
    nodes as XML entities so Qt TS files keep their original escaping style.
    """
    original_escape_cdata = getattr(xml.etree.ElementTree, "_escape_cdata")

    def escape_cdata_with_entities(text):
        return (
            original_escape_cdata(text)
            .replace('"', '&quot;')
            .replace("'", '&apos;')
        )

    setattr(xml.etree.ElementTree, "_escape_cdata", escape_cdata_with_entities)
    try:
        yield
    finally:
        setattr(xml.etree.ElementTree, "_escape_cdata", original_escape_cdata)


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
        replacement = replace_numerus_translation(
            translation_indent,
            updated_attributes,
            inner_content,
            escaped_translation,
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


def replace_numerus_translation(
    translation_indent,
    updated_attributes,
    inner_content,
    escaped_translation,
):
    """
    Fill existing Qt numerusform slots without changing their count.

    Qt TS plural form counts depend on the target language. The TS file usually
    already carries the right number of ``numerusform`` elements, so keep that
    structure and place the translated text into each existing slot.
    """
    numerus_matches = list(NUMERUS_FORM_PATTERN.finditer(inner_content))
    if not numerus_matches:
        numerusform_indent = f"{translation_indent}    "
        return (
            f"{translation_indent}<translation{updated_attributes}>\n"
            f"{numerusform_indent}<numerusform>{escaped_translation}</numerusform>\n"
            f"{translation_indent}</translation>"
        )

    updated_parts = []
    last_index = 0
    for numerus_match in numerus_matches:
        updated_parts.append(inner_content[last_index:numerus_match.start()])
        updated_parts.append(
            f"{numerus_match.group(1)}{escaped_translation}{numerus_match.group(3)}"
        )
        last_index = numerus_match.end()
    updated_parts.append(inner_content[last_index:])

    return (
        f"{translation_indent}<translation{updated_attributes}>"
        f"{''.join(updated_parts)}</translation>"
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
    Replace the first two lines of a file with the XML declaration and DOCTYPE.

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
    Translate a single string with the configured backend.

    :param source_string: The string to translate.
    :type source_string: str
    :param source_language: The ISO 639-1 code of the language to translate from.
    :type source_language: str
    :param target_language: The ISO 639-1 code of the language to translate to.
    :type target_language: str
    :return: The translated string.
    :rtype: str
    """
    start_time = time.time()
    translators = importlib.import_module("translators")
    output, backend = translate_with_configured_backends(
        translators,
        source_string,
        source_language,
        target_language,
    )
    print(
        f"translateString[{backend}]: {format_duration_seconds(time.time() - start_time)} : "
        f"{source_string} -> {output} "
        f"({source_language} -> {target_language})"
    )

    return output


def translate_with_configured_backends(
    translators,
    source_string,
    source_language,
    target_language,
):
    """
    Try the configured translator backends in order and return the first result.
    """
    failures = []
    for backend in TRANSLATION_BACKENDS:
        try:
            return (
                translators.translate_text(
                    source_string,
                    translator=backend,
                    from_language=source_language,
                    to_language=target_language,
                    timeout=TRANSLATION_TIMEOUT_SECONDS,
                ),
                backend,
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            failures.append(f"{backend}: {error}")

    joined_failures = "; ".join(failures)
    raise TranslationBackendError(
        f"All translation backends failed for {source_language} -> {target_language}: "
        f"{joined_failures}"
    )


def format_translation_backends():
    """
    Return a human-readable backend fallback chain.
    """
    return " -> ".join(TRANSLATION_BACKENDS)


def format_duration_seconds(seconds):
    """
    Format elapsed seconds with one decimal place, truncating extra precision.
    """
    return f"{int(seconds * 10) / 10:.1f}s"


def format_run_summary(summary):
    """
    Format a compact end-of-run summary for terminal output.
    """
    return (
        "Run summary:\n"
        f"CuteLingoExpress: {PROJECT_URL}\n"
        f"Version: {summary['version']}\n"
        f"Language direction: {summary['source_language']} -> {summary['target_language']}\n"
        f"Backend: {summary['backend']}\n"
        f"Messages scanned: {summary['messages_scanned']}\n"
        f"Unfinished strings before: {summary['unfinished_before']}\n"
        f"Translated strings: {summary['translated_count']}\n"
        f"Numerus translations: {summary['numerus_translated_count']}\n"
        f"Skipped strings: {summary['skipped_count']}\n"
        "Average translation time: "
        f"{format_duration_seconds(summary['average_translation_seconds'])}\n"
        f"Overall runtime: {format_duration_seconds(summary['runtime_seconds'])}"
    )


def process_message_translation(message, source_language, target_language):
    """
    Translate a single unfinished TS message and return summary data for it.
    """
    numerus = message.attrib.get('numerus') == 'yes'
    translation = message.find('translation')
    if translation is None or translation.attrib.get('type') != 'unfinished':
        return None, False, False, 0.0

    source_text = message.find('source').text
    translation_start = time.time()
    translated_text = translate_string(source_text, source_language, target_language)
    elapsed_seconds = time.time() - translation_start
    return (
        {
            'translated_text': translated_text,
            'numerus': numerus,
        },
        True,
        numerus,
        elapsed_seconds,
    )


def build_transform_summary(summary, translated_count):
    """
    Finalize run statistics for a TS translation pass.
    """
    return {
        'messages_scanned': summary['messages_scanned'],
        'unfinished_before': summary['unfinished_before'],
        'translated_count': translated_count,
        'numerus_translated_count': summary['numerus_translated_count'],
        'skipped_count': summary['unfinished_before'] - translated_count,
        'average_translation_seconds': (
            summary['total_translation_seconds'] / translated_count if translated_count else 0.0
        ),
    }


def transform_ts_file(ts_file_path, _language, target_language):
    """
    Transform a `.ts` file by translating all unfinished messages.

    The translated messages replace the original messages in the same file.

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
    summary = {
        'messages_scanned': 0,
        'unfinished_before': 0,
        'numerus_translated_count': 0,
        'total_translation_seconds': 0.0,
    }

    for message in root.iter('message'):
        summary['messages_scanned'] += 1
        translation_result, was_unfinished, was_numerus, elapsed_seconds = (
            process_message_translation(message, _language, target_language)
        )
        translated_messages.append(translation_result)
        if was_unfinished:
            summary['unfinished_before'] += 1
            summary['total_translation_seconds'] += elapsed_seconds
        if was_numerus:
            summary['numerus_translated_count'] += 1

    updated_content = update_ts_content(original_content, translated_messages)
    with open(ts_file_path, 'w', encoding='utf-8') as file:
        file.write(updated_content)

    print("TS file transformed successfully.")
    translated_count = sum(1 for item in translated_messages if item is not None)
    return build_transform_summary(summary, translated_count)


def main():
    """
    Run the command-line interface for translating a Qt `.ts` file in place.
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
    source_language = sys.argv[2]
    target_language = sys.argv[3]
    start_time = time.time()
    transform_stats = transform_ts_file(ts_file_path, source_language, target_language)
    runtime_seconds = time.time() - start_time
    print(
        format_run_summary(
            {
                'version': VERSION,
                'source_language': source_language,
                'target_language': target_language,
                'backend': format_translation_backends(),
                'messages_scanned': transform_stats['messages_scanned'],
                'unfinished_before': transform_stats['unfinished_before'],
                'translated_count': transform_stats['translated_count'],
                'numerus_translated_count': transform_stats['numerus_translated_count'],
                'skipped_count': transform_stats['skipped_count'],
                'average_translation_seconds': transform_stats['average_translation_seconds'],
                'runtime_seconds': runtime_seconds,
            }
        )
    )


if __name__ == "__main__":
    main()

# Example output from a manual run:
# python auto_trans.py testing/helloworld.ts en cn
#
# Using Germany server backend.
# translateString[google]: 1.3s : Hello world! -> 你好世界！ (en -> cn)
# translateString[google]: 1.9s : My first dish. -> 我的第一道菜。 (en -> cn)
# translateString[google]: 2.1s : white bread with butter -> 白面包和黄油 (en -> cn)
# TS file transformed successfully.
# Overall runtime: 5.4s
# (venv) [mpetrick@marcel-precision3551 AutoTrans]$

# Manual test commands:
# python auto_trans.py testing/numerus.ts de cn
# python auto_trans.py testing/helloworld.ts en cn
