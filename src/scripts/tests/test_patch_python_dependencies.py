from pathlib import Path

import pytest

from scripts.patch_python_dependencies import replace_once, write_exact


def test_replace_once(tmp_path: Path) -> None:
    target = tmp_path / "dependency.py"
    target.write_text("before broken after\n", encoding="utf-8")

    replace_once(target, "broken", "fixed")

    assert target.read_text(encoding="utf-8") == "before fixed after\n"


@pytest.mark.parametrize("content", ["no match", "broken and broken"])
def test_replace_once_rejects_unexpected_source(tmp_path: Path, content: str) -> None:
    target = tmp_path / "dependency.py"
    target.write_text(content, encoding="utf-8")

    with pytest.raises(RuntimeError, match="expected exactly one occurrence"):
        replace_once(target, "broken", "fixed")


def test_write_exact_creates_file_and_accepts_identical_content(tmp_path: Path) -> None:
    target = tmp_path / "migration.py"

    write_exact(target, "generated migration\n")
    write_exact(target, "generated migration\n")

    assert target.read_text(encoding="utf-8") == "generated migration\n"


def test_write_exact_rejects_unexpected_existing_content(tmp_path: Path) -> None:
    target = tmp_path / "migration.py"
    target.write_text("upstream migration\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unexpected existing content"):
        write_exact(target, "generated migration\n")
