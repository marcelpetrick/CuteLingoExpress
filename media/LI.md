# Good news: CuteLingoExpress 0.3.0 adds optional LVGL YAML translation

## Today’s changes

- CuteLingoExpress now supports LVGL-style YAML translation alongside its established Qt TS workflow.
- YAML support is optional, keeping the main Python and Qt translation experience lightweight.
- The new mode is invoked explicitly with `--lvgl-yaml`, so existing usage remains unchanged.
- Only translatable YAML values are processed; keys and the document hierarchy stay intact.
- Comments, quotes, block scalars, anchors, aliases, lists, numbers, booleans, and null values are preserved.
- Source YAML files remain untouched; translated content is written safely to a separate language-specific file.
- The feature reuses the existing translation backends, timeout handling, and automatic fallback chain.
- Dependencies are pinned, including the optional YAML parser, for predictable and reproducible builds.
- The documentation, packaging, local pipeline, and GitHub release workflow were updated for version 0.3.0.
- Quality remains measurable: 58 automated tests, 100% statement and branch coverage, Pylint 10/10, and a green CI pipeline.

## Why continuous market review and adaptation matter

- Customer workflows evolve, and supporting the formats they actually use keeps a product relevant.
- Regular market observation reveals valuable adjacent needs without losing sight of the core product purpose.
- Competitors, platforms, dependencies, and technical standards change continuously; software must respond deliberately.
- Early feedback helps validate demand before a side feature grows into expensive or distracting complexity.
- Optional capabilities make it possible to explore new opportunities while protecting existing users from unnecessary change.
