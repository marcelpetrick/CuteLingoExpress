# Repository review record

Reviewed on 2026-09-20 against the complete repository at `a1a8a86`, including
code, architecture, CI, and documentation. This replaces the earlier undated
review, whose claim that the repository had no CI was incorrect.

## Corrections verified by regression tests

- TS writes use an atomic replacement and preserve file permissions and symlink
  targets; failed writes leave the original catalog intact.
- A translation target that conflicts with catalog metadata is rejected.
- The package import gate propagates Python failures.
- XML parsing supplies both structured elements and byte positions for rewriting,
  so comments and compact formatting do not select the wrong translation.
- Self-closing plural slots survive translation.
- Qt byte elements and following text are decoded; absent or blank sources remain
  unfinished and are counted as skipped.
- Unsupported length variants are rejected before replacement.
- The unfinished attribute is removed regardless of quoting, spacing, or numeric
  character references, without changing other attribute values.
- Filename source prefixes are checked against ISO 639-1 identifiers.
- YAML merges retain inheritance, and anchors shared between keys and values are
  split without duplicate names or changes to mapping keys.
- Invalid CLI arguments return a nonzero status.
- Release publication can resume when an existing tag points to the same commit.
- TS line endings and missing final newlines are retained; unchanged catalogs are
  not rewritten.

Regression cases live in [test_regressions.py](test_regressions.py), alongside the
existing [TS tests](test_auto_trans.py) and [YAML tests](test_auto_trans_yaml.py).
The [local pipeline](localPipeline.sh) runs lint, tests, coverage, package builds,
wheel installation, and import checks. GitHub also has a
[validation workflow](.github/workflows/local-pipeline.yml) and a
[release workflow](.github/workflows/release.yml).

## Remaining product limitations

- Translation uses unofficial third-party services. A backend can become
  unavailable independently of this repository; automated unit tests isolate
  that variability, while real-backend checks must be run separately.
- An interrupted translation run has no checkpoint/resume facility. Before the
  final write, failure leaves the original TS file unchanged; completed remote
  translation calls must be repeated on retry.
- Length variants require manual translation. Plural slot counts are preserved,
  but one machine-translated phrase is reused across slots and requires linguistic
  review.
- Translation helpers print progress to stdout. There is no structured logging
  interface or configurable output path for TS mode.
