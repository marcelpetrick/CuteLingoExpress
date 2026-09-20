"""
Translate unfinished entries in Qt `.ts` files.

The script uses the `translators` library to translate individual source
strings and writes the updated translations back to the original file.
"""

import sys
import importlib
import re
import time
import os
import stat
import xml.etree.ElementTree
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.sax.saxutils import escape

from version import VERSION, get_startup_banner
from ts_xml import PositionedXml


__version__ = VERSION
PROJECT_URL = "https://github.com/marcelpetrick/CuteLingoExpress"
TRANSLATION_BACKENDS = ("google", "bing", "myMemory")
AUTO_DETECTION_BACKENDS = frozenset(("google", "bing"))
TRANSLATION_TIMEOUT_SECONDS = 20.0

FILENAME_LANGUAGE_PATTERN = re.compile(
    r"(?:^|[_.-])(?P<language>[a-z]{2,3})(?:[_-](?P<territory>[A-Z]{2}))?$"
)
FILENAME_LANGUAGE_PAIR_PATTERN = re.compile(
    r"(?:^|[_.-])(?P<source>[a-z]{2})[_.-](?P<target>[a-z]{2,3})$"
)
# ISO 639-1 identifiers from pycountry’s ISO 639-3 database.
SOURCE_LANGUAGE_CODES = frozenset((
    "aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch "
    "co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy "
    "ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it "
    "iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo "
    "lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny "
    "oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg sh si sk "
    "sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw "
    "ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu "
).split())

TRANSLATOR_LOCALE_OVERRIDES = {
    "fa_AF": "fa-AF",
    "fr_CA": "fr-CA",
    "pt_PT": "pt-PT",
    "zh_CN": "zh-CN",
    "zh_TW": "zh-TW",
}


class TranslationBackendError(RuntimeError):
    """
    Raised when all configured translation backends fail for a source string.
    """


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
    return ''.join(
        f'<byte value="x{ord(character):x}"/>'
        if ord(character) < 32 and character not in '\t\n\r'
        else escape(character, entity_map)
        for character in text
    )


def remove_unfinished_type(attributes_text):
    """
    Remove the ``type="unfinished"`` attribute while preserving any other
    translation attributes.
    """
    element = xml.etree.ElementTree.fromstring(f'<translation{attributes_text}/>')
    attributes = re.compile(r"""\s+([\w:.-]+)\s*=\s*(?:"[^"]*"|'[^']*')""")
    updated_attributes = attributes.sub(
        lambda match: '' if match.group(1) == 'type' and element.get('type') == 'unfinished'
        else match.group(0), attributes_text,
    ).strip()
    return f' {updated_attributes}' if updated_attributes else ''



def replace_translation_in_message(message_block, translated_text, numerus):
    """
    Replace the unfinished translation inside a single message block while
    leaving all unrelated XML untouched.
    """
    document = PositionedXml(message_block)
    source_span = document.root.find('source')
    translation_span = document.root.find('translation')
    if source_span is None or translation_span is None:
        raise ValueError("Unable to locate source or translation block in TS message.")

    validate_translation_structure(translation_span.element)
    source_raw = document.text(source_span.open_end, source_span.close_start)
    prefix = document.text(0, translation_span.start).rsplit('\n', maxsplit=1)[-1]
    translation_indent = prefix if not prefix.strip() else ''
    opening_tag = document.text(translation_span.start, translation_span.open_end)
    attributes = opening_tag[len('<translation'):].removesuffix('>').removesuffix('/')
    updated_attributes = remove_unfinished_type(attributes)
    inner_content = document.text(translation_span.open_end, translation_span.close_start)

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
        document.text(0, translation_span.start)
        + replacement[len(translation_indent):]
        + document.text(translation_span.end, len(document.data))
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
    document = PositionedXml(f'<translation>{inner_content}</translation>')
    numerus_matches = [child for child in document.root.children
                       if child.element.tag == 'numerusform']
    if not numerus_matches:
        numerusform_indent = f"{translation_indent}    "
        return (
            f"{translation_indent}<translation{updated_attributes}>\n"
            f"{numerusform_indent}<numerusform>{escaped_translation}</numerusform>\n"
            f"{translation_indent}</translation>"
        )

    updated_parts = []
    last_index = document.root.open_end
    for numerus_match in numerus_matches:
        updated_parts.append(document.text(last_index, numerus_match.start))
        opening = document.text(numerus_match.start, numerus_match.open_end)
        if opening.endswith('/>'):
            opening = opening[:-2].rstrip() + '>'
        updated_parts.append(f'{opening}{escaped_translation}</numerusform>')
        last_index = numerus_match.end
    updated_parts.append(document.text(last_index, document.root.close_start))

    return (
        f"{translation_indent}<translation{updated_attributes}>"
        f"{''.join(updated_parts)}</translation>"
    )


def update_ts_content(original_content, translated_messages, document=None):
    """
    Apply translation updates to the original TS file content without
    reserializing untouched XML.
    """
    updated_parts = []
    last_index = 0
    document = document or PositionedXml(original_content)
    message_matches = list(document.iter('message'))

    if len(message_matches) != len(translated_messages):
        raise ValueError("TS message count changed while processing the file.")

    for message_match, message_update in zip(message_matches, translated_messages):
        updated_parts.append(document.text(last_index, message_match.start))
        message_block = document.text(message_match.start, message_match.end)

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

        last_index = message_match.end

    updated_parts.append(document.text(last_index, len(document.data)))
    updated_content = ''.join(updated_parts)
    return updated_content


def get_help_text() -> str:
    """
    Return a concise help message for the command line interface.
    """
    return (
        "Translate unfinished entries in a Qt .ts file in place.\n"
        "\n"
        "Usage: python auto_trans.py <ts_file_path> [source_language] [target_language]\n"
        "       python auto_trans.py --lvgl-yaml <yaml_file> <source_language> "
        "<target_language>\n"
        "\n"
        "Languages are read from Qt TS metadata or the filename when omitted.\n"
        "The source falls back to automatic detection.\n"
        "\n"
        "Examples:\n"
        "  python auto_trans.py translations/app_de.ts\n"
        "  python auto_trans.py testing/helloworld.ts en de\n"
        "  python auto_trans.py --lvgl-yaml translations/osd_en.yaml en de\n"
        "  python auto_trans.py --help\n"
    )


def normalize_qt_language(language):
    """
    Convert a Qt locale identifier to a language accepted by the translators.
    """
    if not language:
        return None

    normalized = language.replace('-', '_')
    if normalized in TRANSLATOR_LOCALE_OVERRIDES:
        return TRANSLATOR_LOCALE_OVERRIDES[normalized]
    return normalized.split('_', maxsplit=1)[0].lower()


def infer_languages_from_filename(ts_file_path):
    """
    Infer source and target languages from conventional TS filename suffixes.
    """
    filename_stem = Path(ts_file_path).stem
    pair_match = FILENAME_LANGUAGE_PAIR_PATTERN.search(filename_stem)
    if pair_match is not None and pair_match.group('source') in SOURCE_LANGUAGE_CODES:
        source_language = normalize_qt_language(pair_match.group('source'))
        target_language = normalize_qt_language(pair_match.group('target'))
        return source_language, target_language

    match = FILENAME_LANGUAGE_PATTERN.search(filename_stem)
    if match is None:
        return None, None

    language = match.group('language')
    territory = match.group('territory')
    qt_locale = f"{language}_{territory}" if territory else language
    return None, normalize_qt_language(qt_locale)


def infer_target_language_from_filename(ts_file_path):
    """
    Return only the inferred target language for callers that need it.
    """
    return infer_languages_from_filename(ts_file_path)[1]


def resolve_languages(ts_file_path, source_language=None, target_language=None):
    """
    Resolve missing languages from Qt TS metadata and the filename.

    Explicit values take precedence. The source uses backend-supported automatic
    detection when the TS file does not declare ``sourcelanguage``.
    """
    root = xml.etree.ElementTree.parse(ts_file_path).getroot()
    filename_source, filename_target = infer_languages_from_filename(ts_file_path)
    resolved_source = source_language or normalize_qt_language(
        root.attrib.get('sourcelanguage')
    ) or filename_source or 'auto'
    resolved_target = target_language or normalize_qt_language(
        root.attrib.get('language')
    ) or filename_target

    if resolved_target is None:
        raise ValueError(
            "Unable to infer the target language from TS metadata or the filename; "
            "provide it explicitly."
        )
    return resolved_source, resolved_target


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
        if source_language == 'auto' and backend not in AUTO_DETECTION_BACKENDS:
            failures.append(f"{backend}: source-language auto detection is unsupported")
            continue
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


def format_translation_backends(source_language=None):
    """
    Return a human-readable backend fallback chain.
    """
    backends = TRANSLATION_BACKENDS
    if source_language == 'auto':
        backends = tuple(
            backend for backend in backends if backend in AUTO_DETECTION_BACKENDS
        )
    return " -> ".join(backends)


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


def read_source_text(source):
    """Decode Qt byte-type mixed content, including text after byte elements."""
    if source is None:
        return ''
    parts = [source.text or '']
    for child in source:
        if child.tag != 'byte':
            raise ValueError(f'Unsupported source element: {child.tag}')
        value = child.attrib['value']
        codepoint = int(value[1:], 16) if value.startswith('x') else int(value)
        parts.extend((chr(codepoint), child.tail or ''))
    return ''.join(parts)


def validate_translation_structure(translation):
    """Preserve unsupported length variants by refusing to replace their content."""
    if any(element.tag == 'lengthvariant' or element.attrib.get('variants') == 'yes'
           for element in translation.iter()):
        raise ValueError('Length variants are not supported; translate this message manually.')


def process_message_translation(message, source_language, target_language):
    """
    Translate a single unfinished TS message and return summary data for it.
    """
    numerus = message.attrib.get('numerus') == 'yes'
    translation = message.find('translation')
    if translation is None or translation.attrib.get('type') != 'unfinished':
        return None, False, False, 0.0

    validate_translation_structure(translation)
    source_text = read_source_text(message.find('source'))
    if not source_text.strip():
        return None, True, False, 0.0
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


def write_ts_content(ts_file_path, content):
    """Replace a catalog atomically, preserving permissions and symlink targets."""
    path = Path(ts_file_path).resolve()
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            'w', encoding='utf-8', newline='', dir=path.parent,
            prefix=f'.{path.name}.', suffix='.tmp', delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.chmod(mode)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def validate_catalog_target(root, target_language):
    """Reject targets that would mix languages in an existing TS catalog."""
    declared = root.attrib.get('language')
    if not declared:
        return
    aliases = {'cn': 'zh-CN', 'zh': 'zh-CN'}
    catalog = normalize_qt_language(declared)
    target = normalize_qt_language(target_language)
    if aliases.get(catalog, catalog) != aliases.get(target, target):
        raise ValueError(
            f'Target language {target_language!r} conflicts with catalog language '
            f'{declared!r}; use a catalog prepared for the requested target.'
        )


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
    with open(ts_file_path, 'r', encoding='utf-8', newline='') as file:
        original_content = file.read()

    document = PositionedXml(original_content)
    root = document.root.element
    validate_catalog_target(root, target_language)
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

    updated_content = update_ts_content(original_content, translated_messages, document)
    if updated_content != original_content:
        write_ts_content(ts_file_path, updated_content)

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

    if len(sys.argv) >= 2 and sys.argv[1] == '--lvgl-yaml':
        if len(sys.argv) != 5:
            print(get_help_text())
            raise SystemExit(2)
        yaml_translation = importlib.import_module('auto_trans_yaml')
        output_path = yaml_translation.translate_yaml_file(
            sys.argv[2],
            sys.argv[3],
            sys.argv[4],
        )
        print(f"LVGL YAML translation written to: {output_path}")
        return

    if len(sys.argv) > 4:
        print(get_help_text())
        raise SystemExit(2)

    ts_file_path = sys.argv[1]
    explicit_source_language = sys.argv[2] if len(sys.argv) >= 3 else None
    explicit_target_language = sys.argv[3] if len(sys.argv) == 4 else None
    source_language, target_language = resolve_languages(
        ts_file_path,
        explicit_source_language,
        explicit_target_language,
    )
    start_time = time.time()
    transform_stats = transform_ts_file(ts_file_path, source_language, target_language)
    runtime_seconds = time.time() - start_time
    print(
        format_run_summary(
            {
                'version': VERSION,
                'source_language': source_language,
                'target_language': target_language,
                'backend': format_translation_backends(source_language),
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
