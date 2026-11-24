"""Exercise the packaged CLI from a fresh directory without translation services."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def smoke_test(command: Path, version: str) -> None:
    """Check startup, Qt TS parsing, and the bundled YAML parser."""
    with TemporaryDirectory() as directory:
        work = Path(directory)
        startup = subprocess.check_output(
            [command, "--version"], cwd=work, text=True, timeout=120,
        )
        if startup.strip() != f"CuteLingoExpress {version}":
            raise RuntimeError(f"Unexpected CLI version {startup!r}")

        catalog = work / "finished.ts"
        catalog.write_text(
            '<TS version="2.1" sourcelanguage="en" language="de">'
            '<context><name>CLI</name><message><source>Hello</source>'
            '<translation>Hallo</translation></message></context></TS>',
            encoding="utf-8",
        )
        subprocess.run([command, catalog], cwd=work, timeout=120, check=True)

        yaml_input = work / "strings.yaml"
        yaml_input.write_text("count: 2\n", encoding="utf-8")
        subprocess.run(
            [command, "--lvgl-yaml", yaml_input, "en", "de"],
            cwd=work, timeout=120, check=True,
        )
        if (work / "strings_de.yaml").read_text(encoding="utf-8") != "count: 2\n":
            raise RuntimeError("Unexpected output from the packaged YAML command")


if __name__ == "__main__":
    os.environ["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    smoke_test(Path(sys.argv[1]).resolve(), sys.argv[2])
