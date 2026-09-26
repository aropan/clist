import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

CONFIGURE_PATH = Path(__file__).resolve().parents[3] / "configure.py"
if not CONFIGURE_PATH.is_file():
    pytestmark = pytest.mark.skip(reason="configure.py is outside the container mount")
else:
    SPEC = importlib.util.spec_from_file_location("configure", CONFIGURE_PATH)
    if SPEC is None or SPEC.loader is None:
        raise ImportError(f"Cannot load {CONFIGURE_PATH}")
    configure = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(configure)
    fill_template = configure.fill_template


def test_fill_template_creates_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path("settings.env.template").write_text("DEFAULT=enabled\nEMPTY=\n", encoding="utf-8")

    fill_template("settings.env", accept_default=True, allow_empty=True)

    assert Path("settings.env").read_text(encoding="utf-8") == "DEFAULT=enabled\nEMPTY=\n"


def test_fill_template_adds_only_missing_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path("settings.env.template").write_text(
        "EXISTING=template\n# Added in a newer template.\nNEW_VALUE=default\nEMPTY_VALUE=\n",
        encoding="utf-8",
    )
    Path("settings.env").write_text("EXISTING=custom\nCUSTOM=keep\n", encoding="utf-8")

    fill_template("settings.env", accept_default=True, allow_empty=True)

    assert Path("settings.env").read_text(encoding="utf-8") == (
        "EXISTING=custom\nCUSTOM=keep\n# Added in a newer template.\nNEW_VALUE=default\nEMPTY_VALUE=\n"
    )


def test_fill_template_preserves_file_without_trailing_newline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path("settings.env.template").write_text("EXISTING=template\nTOKEN=\n", encoding="utf-8")
    Path("settings.env").write_text("EXISTING=custom", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "new-token")

    fill_template("settings.env")

    assert Path("settings.env").read_text(encoding="utf-8") == "EXISTING=custom\nTOKEN=new-token\n"


def test_fill_template_adds_complete_multiline_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path("settings.py.template").write_text(
        'EXISTING = "template"\n\nNEW_MAPPING = {\n    "key": "value",\n}\n\nAFTER = True\n',
        encoding="utf-8",
    )
    Path("settings.py").write_text('EXISTING = "custom"\n', encoding="utf-8")

    fill_template("settings.py")

    assert Path("settings.py").read_text(encoding="utf-8") == (
        'EXISTING = "custom"\n\nNEW_MAPPING = {\n    "key": "value",\n}\n\nAFTER = True\n'
    )


def test_fill_template_leaves_up_to_date_file_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path("settings.env.template").write_text("VALUE=template\n", encoding="utf-8")
    Path("settings.env").write_text("# Local comment\nVALUE=custom", encoding="utf-8")

    fill_template("settings.env")

    assert Path("settings.env").read_text(encoding="utf-8") == "# Local comment\nVALUE=custom"


def test_create_admin_passes_password_as_argument_without_logging_it(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock()
    log = Mock()
    monkeypatch.setattr(configure.subprocess, "run", run)
    monkeypatch.setattr(configure.logger, "info", log)

    password = 'secret"; $(echo exposed)'
    configure.create_admin("admin", password, "admin@example.com")

    run.assert_called_once_with(
        [
            "docker",
            "compose",
            "run",
            "dev",
            "./manage.py",
            "createadmin",
            "--username",
            "admin",
            "--password",
            password,
            "--email",
            "admin@example.com",
            "--noinput",
        ],
        check=True,
    )
    assert password not in str(log.call_args_list)


def test_password_prompt_requires_a_nonempty_value(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = Mock(side_effect=["", "entered-secret"])
    monkeypatch.setattr(configure, "getpass", prompt)

    assert configure.enter_value("password", None, secret=True) == "entered-secret"
    assert prompt.call_count == 2
    assert prompt.call_args.args[0] == "Enter password: "
