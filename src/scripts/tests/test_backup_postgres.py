import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from rich.console import Console

from scripts import backup_postgres
from scripts.backup_postgres import (
    BackupApplication,
    BackupConfig,
    BackupError,
    CopyProgress,
    DatabaseInfo,
    DumpProgressTracker,
    PostgresClient,
    TableInfo,
    archive_component,
    build_parser,
    config_from_args,
    connection_arguments,
    expired_backup_directories,
    remove_in_progress,
    sanitize_text,
    validate_dump_versions,
    write_checksums,
)


@pytest.fixture
def backup_config(tmp_path: Path) -> BackupConfig:
    return BackupConfig(
        root=tmp_path,
        host="db",
        port="5432",
        user="backup-user",
        password="private-backup-password",
        admin_database="clistdb",
        jobs=2,
        compression=6,
        retention_days=7,
        dry_run=False,
        allow_low_space=False,
    )


def write_manifest(path: Path, *, completed_at: datetime, status: str = "complete") -> None:
    path.mkdir()
    (path / "manifest.json").write_text(
        json.dumps({
            "status": status,
            "backup_name": path.name,
            "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        }),
        encoding="utf-8",
    )


def test_cli_defaults_and_validation() -> None:
    parser = build_parser()

    args = parser.parse_args([])

    assert args.jobs == 2
    assert args.compression == 6
    assert args.retention_days == 7
    assert not args.dry_run
    with pytest.raises(SystemExit) as jobs_error:
        parser.parse_args(["--jobs", "0"])
    assert jobs_error.value.code == 2
    with pytest.raises(SystemExit) as compression_error:
        parser.parse_args(["--compression", "10"])
    assert compression_error.value.code == 2


def test_config_requires_connection_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_parser()
    for name in ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(BackupError, match="POSTGRES_HOST"):
        config_from_args(parser.parse_args([]))


def test_newer_pg_dump_can_dump_older_server() -> None:
    validate_dump_versions(client_major=18, server_major=14)
    validate_dump_versions(client_major=18, server_major=18)


def test_older_pg_dump_cannot_dump_newer_server() -> None:
    with pytest.raises(BackupError, match="older than"):
        validate_dump_versions(client_major=14, server_major=18)


def test_main_reports_backup_error_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(backup_postgres, "config_from_args", Mock(side_effect=BackupError("expected failure")))

    assert backup_postgres.main([]) == 1

    assert "expected failure" in capsys.readouterr().err


def test_password_is_only_passed_via_environment(backup_config: BackupConfig) -> None:
    client = PostgresClient(backup_config)

    arguments = connection_arguments(backup_config)

    assert backup_config.password not in arguments
    assert client.environment()["PGPASSWORD"] == backup_config.password
    assert backup_config.password not in sanitize_text(
        f"connection failed with {backup_config.password}",
        [backup_config.password],
    )


def test_command_errors_redact_password(backup_config: BackupConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    result = Mock(returncode=1, stdout="", stderr=f"authentication failed: {backup_config.password}")
    monkeypatch.setattr(backup_postgres.subprocess, "run", lambda *args, **kwargs: result)

    with pytest.raises(BackupError) as error:
        PostgresClient(backup_config).checked_capture(["psql"])

    assert backup_config.password not in str(error.value)
    assert "<redacted>" in str(error.value)


def test_dump_commands_include_complete_directory_archive_options(backup_config: BackupConfig, tmp_path: Path) -> None:
    command = PostgresClient(backup_config).database_dump_command("service db", tmp_path / "archive")

    assert "--format=directory" in command
    assert "--jobs=2" in command
    assert "--compress=6" in command
    assert "--verbose" in command
    assert command[-1] == "service db"
    assert backup_config.password not in command


def test_archive_component_is_safe_and_collision_resistant_by_index() -> None:
    assert archive_component(1, "normal_db") == "001-normal_db"
    assert archive_component(2, "../../odd database") == "002-odd_database"
    assert archive_component(3, "💾") == "003-database"


def test_progress_tracker_weights_completed_and_active_tables() -> None:
    first = TableInfo(relid=11, name="public.first", size_bytes=100, estimated_rows=100)
    second = TableInfo(relid=12, name="public.second", size_bytes=300, estimated_rows=300)
    database = DatabaseInfo(
        oid=1,
        name="app",
        size_bytes=1000,
        archive_name="001-app",
        tables={first.relid: first, second.relid: second},
    )
    tracker = DumpProgressTracker(database)

    completed, active = tracker.update([CopyProgress(11, first.name, 50, 50)])
    assert completed == 50
    assert active == [first.name]

    completed, active = tracker.update([CopyProgress(12, second.name, 150, 150)])
    assert completed == 250
    assert active == [second.name]

    completed, active = tracker.update([])
    assert completed == 396
    assert active == []


def test_progress_tracker_clamps_stale_row_estimates() -> None:
    table = TableInfo(relid=11, name="public.data", size_bytes=100, estimated_rows=10)
    database = DatabaseInfo(1, "app", 100, "001-app", {table.relid: table})

    completed, _ = DumpProgressTracker(database).update([CopyProgress(11, table.name, 1000, 1000)])

    assert completed == 98


def test_write_checksums_covers_manifest_and_archive_files(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}\n", encoding="utf-8")
    archive = tmp_path / "databases" / "001-app"
    archive.mkdir(parents=True)
    (archive / "toc.dat").write_bytes(b"toc")
    processed = 0

    def on_bytes(value: int) -> None:
        nonlocal processed
        processed += value

    checksum_path = write_checksums(tmp_path, on_bytes)

    checksums = checksum_path.read_text(encoding="utf-8")
    assert "manifest.json" in checksums
    assert "databases/001-app/toc.dat" in checksums
    assert "SHA256SUMS" not in checksums
    assert processed == len(b"{}\n") + len(b"toc")
    assert checksum_path.stat().st_mode & 0o777 == 0o600


def test_retention_selects_only_old_verified_directories(tmp_path: Path) -> None:
    now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    old = tmp_path / "postgresql-20260701T120000Z"
    recent = tmp_path / "postgresql-20260809T120000Z"
    incomplete = tmp_path / "postgresql-20260601T120000Z"
    bad_status = tmp_path / "postgresql-20260501T120000Z"
    write_manifest(old, completed_at=now - timedelta(days=40))
    write_manifest(recent, completed_at=now - timedelta(days=1))
    incomplete.mkdir()
    write_manifest(bad_status, completed_at=now - timedelta(days=60), status="in-progress")
    outside = tmp_path.parent / f"{tmp_path.name}-outside-backup"
    outside.mkdir()
    symlink = tmp_path / "postgresql-20260401T120000Z"
    symlink.symlink_to(outside, target_is_directory=True)

    expired = expired_backup_directories(tmp_path, now=now, retention_days=7)

    assert expired == [old]
    assert outside.is_dir()


def test_rotation_removes_only_selected_backup(backup_config: BackupConfig) -> None:
    now = datetime.now(timezone.utc)
    old = backup_config.root / "postgresql-20260701T120000Z"
    recent = backup_config.root / "postgresql-20990101T120000Z"
    write_manifest(old, completed_at=now - timedelta(days=40))
    write_manifest(recent, completed_at=now)
    (old / "data").write_bytes(b"old")
    console_output = io.StringIO()
    application = BackupApplication(backup_config, Console(file=console_output, force_terminal=False))

    application.rotate_backups()

    assert not old.exists()
    assert recent.exists()
    assert "removed postgresql-20260701T120000Z" in console_output.getvalue()


def test_in_progress_cleanup_cannot_escape_backup_root(tmp_path: Path) -> None:
    valid = tmp_path / ".postgresql-20260810T120000Z.in-progress"
    valid.mkdir()
    (valid / "partial").write_bytes(b"partial")
    outside_root = tmp_path.parent / f"{tmp_path.name}-outside-root"
    outside_root.mkdir()
    outside = outside_root / ".postgresql-20260810T130000Z.in-progress"
    outside.mkdir()
    symlink = tmp_path / ".postgresql-20260810T140000Z.in-progress"
    symlink.symlink_to(outside, target_is_directory=True)

    assert remove_in_progress(valid, tmp_path)
    assert not valid.exists()
    assert not remove_in_progress(outside, tmp_path)
    assert outside.exists()
    assert not remove_in_progress(symlink, tmp_path)
    assert symlink.is_symlink()


def test_dry_run_never_starts_dump_or_creates_backup_directory(
    backup_config: BackupConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BackupConfig(**{**backup_config.__dict__, "dry_run": True})
    application = BackupApplication(config, Console(file=io.StringIO(), force_terminal=False))
    database = DatabaseInfo(1, "app", 1, "001-app")
    dump_globals = Mock()
    dump_databases = Mock()
    monkeypatch.setattr(application, "preflight", lambda: [database])
    monkeypatch.setattr(application, "dump_globals", dump_globals)
    monkeypatch.setattr(application, "dump_databases", dump_databases)

    result = application.run()

    assert result is None
    dump_globals.assert_not_called()
    dump_databases.assert_not_called()
    assert not list(backup_config.root.glob("postgresql-*"))
    assert not list(backup_config.root.glob(".postgresql-*.in-progress"))


def test_failed_dump_removes_only_current_in_progress_directory(
    backup_config: BackupConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = BackupApplication(backup_config, Console(file=io.StringIO(), force_terminal=False))
    database = DatabaseInfo(1, "app", 1, "001-app")
    existing = backup_config.root / "postgresql-20260101T000000Z"
    write_manifest(existing, completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(application, "preflight", lambda: [database])
    monkeypatch.setattr(application, "dump_globals", Mock(side_effect=BackupError("expected failure")))

    with pytest.raises(BackupError, match="expected failure"):
        application.run()

    assert existing.exists()
    assert not list(backup_config.root.glob(".postgresql-*.in-progress"))
