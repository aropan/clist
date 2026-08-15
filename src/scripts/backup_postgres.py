#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

BACKUP_NAME_RE = re.compile(r"^postgresql-\d{8}T\d{6}Z$")
IN_PROGRESS_NAME_RE = re.compile(r"^\.postgresql-\d{8}T\d{6}Z\.in-progress$")
CONTROLLED_APP_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
READ_CHUNK_SIZE = 1024 * 1024


class BackupError(RuntimeError):
    pass


class BackupInterrupted(BackupError):
    pass


@dataclass(frozen=True)
class BackupConfig:
    root: Path
    host: str
    port: str
    user: str
    password: str
    admin_database: str
    jobs: int
    compression: int
    retention_days: int
    dry_run: bool
    allow_low_space: bool


@dataclass(frozen=True)
class TableInfo:
    relid: int
    name: str
    size_bytes: int
    estimated_rows: float


@dataclass(frozen=True)
class DatabaseInfo:
    oid: int
    name: str
    size_bytes: int
    archive_name: str
    tables: dict[int, TableInfo] = field(default_factory=dict, compare=False)

    @property
    def progress_weight(self) -> int:
        table_bytes = sum(table.size_bytes for table in self.tables.values())
        return max(table_bytes, self.size_bytes if not self.tables else 0, 1)


@dataclass(frozen=True)
class CopyProgress:
    relid: int
    name: str
    bytes_processed: int
    tuples_processed: int


@dataclass(frozen=True)
class DatabaseBackupResult:
    database: DatabaseInfo
    archive_path: Path
    archive_size_bytes: int
    duration_seconds: float


class DumpProgressTracker:
    def __init__(self, database: DatabaseInfo) -> None:
        self.database = database
        self.seen_relids: set[int] = set()
        self.completed_relids: set[int] = set()

    def update(self, active: Sequence[CopyProgress]) -> tuple[int, list[str]]:
        active_relids = {item.relid for item in active if item.relid}
        self.completed_relids.update(self.seen_relids - active_relids)
        self.seen_relids.update(active_relids)

        completed = sum(
            self.database.tables[relid].size_bytes for relid in self.completed_relids if relid in self.database.tables
        )
        active_names = []
        for item in active:
            table = self.database.tables.get(item.relid)
            active_names.append(item.name)
            if table is None:
                continue
            if table.estimated_rows > 0:
                fraction = item.tuples_processed / table.estimated_rows
            elif table.size_bytes > 0:
                fraction = item.bytes_processed / table.size_bytes
            else:
                fraction = 0
            completed += int(table.size_bytes * min(max(fraction, 0), 0.98))

        return min(completed, int(self.database.progress_weight * 0.99)), active_names


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def compression_level(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 9:
        raise argparse.ArgumentTypeError("must be between 0 and 9")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def validate_dump_versions(client_major: int, server_major: int) -> None:
    if client_major < server_major:
        raise BackupError(
            f"pg_dump major version {client_major} is older than PostgreSQL server major version {server_major}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back up every non-template PostgreSQL database")
    parser.add_argument(
        "--jobs",
        type=positive_int,
        default=2,
        help="parallel pg_dump workers per database (default: 2)",
    )
    parser.add_argument(
        "--compression",
        type=compression_level,
        default=6,
        help="pg_dump compression level from 0 to 9 (default: 6)",
    )
    parser.add_argument(
        "--retention-days",
        type=nonnegative_int,
        default=7,
        help="remove verified backups older than this; 0 disables rotation (default: 7)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run discovery and report actions without writing or deleting",
    )
    parser.add_argument(
        "--allow-low-space",
        action="store_true",
        help="continue when free space is smaller than the physical size of all source databases",
    )
    return parser


def required_environment(name: str) -> str:
    if name not in os.environ or not os.environ[name]:
        raise BackupError(f"required environment variable is not set: {name}")
    return os.environ[name]


def config_from_args(args: argparse.Namespace) -> BackupConfig:
    return BackupConfig(
        root=Path(os.environ.get("BACKUP_ROOT", "/backups")),
        host=required_environment("POSTGRES_HOST"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=required_environment("POSTGRES_USER"),
        password=required_environment("POSTGRES_PASSWORD"),
        admin_database=required_environment("POSTGRES_DB"),
        jobs=args.jobs,
        compression=args.compression,
        retention_days=args.retention_days,
        dry_run=args.dry_run,
        allow_low_space=args.allow_low_space,
    )


def human_size(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PiB"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_name(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_manifest_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def archive_component(index: int, database_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", database_name).strip("._-") or "database"
    return f"{index:03d}-{slug[:80]}"


def sanitize_text(value: str, secrets: Sequence[str]) -> str:
    sanitized = value
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "<redacted>")
    return sanitized


def error_tail(value: str, secrets: Sequence[str], limit: int = 4000) -> str:
    sanitized = sanitize_text(value.strip(), secrets)
    if len(sanitized) > limit:
        sanitized = f"…{sanitized[-limit:]}"
    return sanitized or "no error details were reported"


def connection_arguments(config: BackupConfig) -> list[str]:
    return [
        "--host",
        config.host,
        "--port",
        config.port,
        "--username",
        config.user,
        "--no-password",
    ]


def directory_size(path: Path) -> int:
    if not path.exists() or path.is_symlink():
        return 0
    total = 0
    for directory, directory_names, file_names in os.walk(path, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = [name for name in directory_names if not (directory_path / name).is_symlink()]
        for file_name in file_names:
            file_path = directory_path / file_name
            try:
                if not file_path.is_symlink():
                    total += file_path.stat().st_size
            except FileNotFoundError:
                continue
    return total


def archive_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if path.name == "SHA256SUMS":
            continue
        if path.is_symlink():
            raise BackupError(f"refusing to checksum symlink in backup: {path.relative_to(root)}")
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def hash_file(path: Path, on_bytes: Callable[[int], None] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(READ_CHUNK_SIZE):
            digest.update(chunk)
            if on_bytes is not None:
                on_bytes(len(chunk))
    return digest.hexdigest()


def write_checksums(root: Path, on_bytes: Callable[[int], None] | None = None) -> Path:
    checksum_path = root / "SHA256SUMS"
    with checksum_path.open("x", encoding="utf-8") as output:
        for path in archive_files(root):
            relative_path = path.relative_to(root).as_posix()
            output.write(f"{hash_file(path, on_bytes)}  {relative_path}\n")
    checksum_path.chmod(0o600)
    return checksum_path


def read_complete_manifest(candidate: Path) -> dict[str, Any] | None:
    manifest_path = candidate / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return None
    try:
        with manifest_path.open(encoding="utf-8") as source:
            manifest = json.load(source)
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(manifest, dict):
        return None
    if manifest.get("status") != "complete" or manifest.get("backup_name") != candidate.name:
        return None
    return manifest


def expired_backup_directories(
    root: Path,
    *,
    now: datetime,
    retention_days: int,
) -> list[Path]:
    if retention_days <= 0 or not root.is_dir():
        return []
    root_resolved = root.resolve()
    cutoff = now.astimezone(timezone.utc) - timedelta(days=retention_days)
    expired = []
    for candidate in root.iterdir():
        if not BACKUP_NAME_RE.fullmatch(candidate.name) or candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            if candidate.resolve().parent != root_resolved:
                continue
        except OSError:
            continue
        manifest = read_complete_manifest(candidate)
        if manifest is None:
            continue
        completed_at = parse_manifest_datetime(manifest.get("completed_at"))
        if completed_at is not None and completed_at < cutoff:
            expired.append(candidate)
    return sorted(expired)


def remove_in_progress(path: Path, root: Path) -> bool:
    if not IN_PROGRESS_NAME_RE.fullmatch(path.name) or path.is_symlink():
        return False
    try:
        if path.resolve().parent != root.resolve() or not path.is_dir():
            return False
    except OSError:
        return False
    shutil.rmtree(path)
    return True


@contextlib.contextmanager
def backup_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".backup.lock"
    with lock_path.open("a+") as lock_file:
        lock_path.chmod(0o600)
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError("another PostgreSQL backup is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class PostgresClient:
    def __init__(self, config: BackupConfig) -> None:
        self.config = config
        self.secrets = [config.password]

    def environment(self, application_name: str | None = None) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PGPASSWORD"] = self.config.password
        environment["PGCONNECT_TIMEOUT"] = "10"
        if application_name is not None:
            environment["PGAPPNAME"] = application_name
        return environment

    def checked_capture(
        self,
        command: Sequence[str],
        *,
        application_name: str | None = None,
        timeout: float | None = None,
    ) -> str:
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=self.environment(application_name),
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackupError(f"failed to run {command[0]}: {sanitize_text(str(exc), self.secrets)}") from exc
        if result.returncode:
            raise BackupError(f"{command[0]} failed: {error_tail(result.stderr, self.secrets)}")
        return result.stdout

    def psql(self, database: str, query: str, *, timeout: float | None = 30) -> str:
        command = [
            "psql",
            "-X",
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
            *connection_arguments(self.config),
            "--dbname",
            database,
            "--command",
            query,
        ]
        return self.checked_capture(command, timeout=timeout).strip()

    def psql_json(self, database: str, query: str, *, timeout: float | None = 30) -> list[dict[str, Any]]:
        output = self.psql(database, query, timeout=timeout)
        try:
            value = json.loads(output or "[]")
        except json.JSONDecodeError as exc:
            raise BackupError("PostgreSQL returned invalid JSON during backup discovery") from exc
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise BackupError("PostgreSQL returned an unexpected result during backup discovery")
        return value

    def wait_until_ready(self, timeout_seconds: int = 30) -> None:
        deadline = time.monotonic() + timeout_seconds
        command = [
            "pg_isready",
            "--host",
            self.config.host,
            "--port",
            self.config.port,
            "--username",
            self.config.user,
            "--dbname",
            self.config.admin_database,
        ]
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=self.environment(),
                )
            except OSError as exc:
                raise BackupError(f"failed to run pg_isready: {sanitize_text(str(exc), self.secrets)}") from exc
            if result.returncode == 0:
                return
            time.sleep(1)
        raise BackupError(f"PostgreSQL did not become ready within {timeout_seconds} seconds")

    def client_major_version(self) -> int:
        output = self.checked_capture(["pg_dump", "--version"], timeout=10)
        match = re.search(r"(\d+)(?:\.\d+)?", output)
        if match is None:
            raise BackupError("could not determine pg_dump version")
        return int(match.group(1))

    def server_major_version(self) -> tuple[int, str]:
        version_num = int(self.psql(self.config.admin_database, "SHOW server_version_num;"))
        version = self.psql(self.config.admin_database, "SHOW server_version;")
        return version_num // 10000, version

    def discover_databases(self) -> list[dict[str, Any]]:
        query = """
            SELECT COALESCE(
                json_agg(
                    json_build_object(
                        'oid', oid,
                        'name', datname,
                        'size_bytes', pg_database_size(oid)
                    ) ORDER BY datname
                ),
                '[]'::json
            )::text
            FROM pg_database
            WHERE datallowconn AND NOT datistemplate;
        """
        return self.psql_json(self.config.admin_database, query)

    def discover_tables(self, database: str) -> dict[int, TableInfo]:
        query = """
            SELECT COALESCE(
                json_agg(
                    json_build_object(
                        'relid', c.oid,
                        'name', format('%I.%I', n.nspname, c.relname),
                        'size_bytes', pg_table_size(c.oid),
                        'estimated_rows', GREATEST(c.reltuples, 0)
                    ) ORDER BY n.nspname, c.relname
                ),
                '[]'::json
            )::text
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'm')
              AND n.nspname <> 'information_schema'
              AND n.nspname NOT LIKE 'pg_%';
        """
        return {
            int(item["relid"]): TableInfo(
                relid=int(item["relid"]),
                name=str(item["name"]),
                size_bytes=int(item["size_bytes"]),
                estimated_rows=float(item["estimated_rows"]),
            )
            for item in self.psql_json(database, query)
        }

    def copy_progress(self, database: str, application_name: str) -> list[CopyProgress]:
        if not CONTROLLED_APP_NAME_RE.fullmatch(application_name):
            raise BackupError("internal backup application name is invalid")
        query = f"""
            SELECT COALESCE(
                json_agg(
                    json_build_object(
                        'relid', progress.relid,
                        'name', COALESCE(format('%I.%I', namespace.nspname, relation.relname), 'large object'),
                        'bytes_processed', progress.bytes_processed,
                        'tuples_processed', progress.tuples_processed
                    ) ORDER BY progress.pid
                ),
                '[]'::json
            )::text
            FROM pg_stat_progress_copy progress
            JOIN pg_stat_activity activity ON activity.pid = progress.pid
            LEFT JOIN pg_class relation ON relation.oid = progress.relid
            LEFT JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
            WHERE progress.command = 'COPY TO'
              AND activity.application_name = '{application_name}';
        """
        return [
            CopyProgress(
                relid=int(item["relid"]),
                name=str(item["name"]),
                bytes_processed=int(item["bytes_processed"]),
                tuples_processed=int(item["tuples_processed"]),
            )
            for item in self.psql_json(database, query, timeout=10)
        ]

    def globals_command(self) -> list[str]:
        return ["pg_dumpall", "--globals-only", *connection_arguments(self.config)]

    def database_dump_command(self, database: str, destination: Path) -> list[str]:
        return [
            "pg_dump",
            "--format=directory",
            f"--jobs={self.config.jobs}",
            f"--compress={self.config.compression}",
            "--verbose",
            f"--file={destination}",
            *connection_arguments(self.config),
            database,
        ]

    def verify_archive(self, archive: Path) -> None:
        self.checked_capture(["pg_restore", "--list", str(archive)], timeout=None)


class BackupApplication:
    def __init__(self, config: BackupConfig, console: Console | None = None) -> None:
        self.config = config
        self.console = console or Console()
        self.client = PostgresClient(config)
        self.display_root = Path(os.environ.get("BACKUP_DISPLAY_ROOT", str(config.root)))
        self.active_process: subprocess.Popen[str] | None = None
        self.started_at = utc_now()
        self.server_version = ""
        self.client_major = 0

    def print_step(self, number: int, title: str) -> None:
        self.console.print(f"\n[bold cyan][{number}/5][/bold cyan] [bold]{title}[/bold]")

    def preflight(self) -> list[DatabaseInfo]:
        self.print_step(1, "Preflight and database discovery")
        with self.console.status("Waiting for PostgreSQL…") as status:
            self.client.wait_until_ready()
            status.update("Checking PostgreSQL versions…")
            self.client_major = self.client.client_major_version()
            server_major, self.server_version = self.client.server_major_version()
            validate_dump_versions(self.client_major, server_major)

            status.update("Discovering databases and table statistics…")
            databases = []
            for index, item in enumerate(self.client.discover_databases(), start=1):
                name = str(item["name"])
                try:
                    tables = self.client.discover_tables(name)
                except BackupError as exc:
                    self.console.print(
                        f"[yellow]Warning:[/yellow] table progress is unavailable for "
                        f"{escape(name)}: {escape(str(exc))}"
                    )
                    tables = {}
                databases.append(
                    DatabaseInfo(
                        oid=int(item["oid"]),
                        name=name,
                        size_bytes=int(item["size_bytes"]),
                        archive_name=archive_component(index, name),
                        tables=tables,
                    )
                )

        if not databases:
            raise BackupError("no connectable non-template PostgreSQL databases were found")

        source_size = sum(database.size_bytes for database in databases)
        free_space = shutil.disk_usage(self.config.root).free
        table = Table(title="PostgreSQL backup set", show_header=True, header_style="bold")
        table.add_column("Database")
        table.add_column("Physical size", justify="right")
        table.add_column("Dump data estimate", justify="right")
        table.add_column("Tables", justify="right")
        for database in databases:
            table.add_row(
                escape(database.name),
                human_size(database.size_bytes),
                f"~{human_size(database.progress_weight)}",
                str(len(database.tables)),
            )
        table.add_section()
        total_dump_data = sum(database.progress_weight for database in databases)
        table.add_row("Total", human_size(source_size), f"~{human_size(total_dump_data)}", "")
        self.console.print(table)
        self.console.print(
            f"PostgreSQL {self.server_version}; pg_dump {self.client_major}; "
            f"free on backup filesystem: [bold]{human_size(free_space)}[/bold]"
        )

        if free_space < source_size:
            warning = (
                f"free space ({human_size(free_space)}) is below the conservative source-size requirement "
                f"({human_size(source_size)})"
            )
            if not self.config.allow_low_space and not self.config.dry_run:
                raise BackupError(f"{warning}; use --allow-low-space to continue explicitly")
            self.console.print(f"[yellow]Warning:[/yellow] {warning}")

        return databases

    def run_checked_process(
        self,
        command: Sequence[str],
        *,
        stdout: Any,
        application_name: str | None = None,
    ) -> None:
        try:
            process = subprocess.Popen(
                command,
                stdout=stdout,
                stderr=subprocess.PIPE,
                text=True,
                env=self.client.environment(application_name),
                start_new_session=True,
            )
        except OSError as exc:
            raise BackupError(f"failed to run {command[0]}: {sanitize_text(str(exc), self.client.secrets)}") from exc
        self.active_process = process
        try:
            _, stderr = process.communicate()
        except BaseException:
            self.terminate_active_process()
            raise
        finally:
            self.active_process = None
        if process.returncode:
            raise BackupError(f"{command[0]} failed: {error_tail(stderr, self.client.secrets)}")

    def terminate_active_process(self) -> None:
        process = self.active_process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except ProcessLookupError, subprocess.TimeoutExpired:
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5)

    def dump_globals(self, destination: Path) -> None:
        self.print_step(2, "Dump PostgreSQL roles and tablespaces")
        with (
            self.console.status("Writing globals.sql directly to the host backup mount…"),
            destination.open("xb") as output,
        ):
            self.run_checked_process(self.client.globals_command(), stdout=output)
        destination.chmod(0o600)
        self.console.print(f"[green]✓[/green] globals.sql ({human_size(destination.stat().st_size)})")

    @staticmethod
    def stderr_reader(stream: Any, messages: queue.Queue[str]) -> None:
        for line in iter(stream.readline, ""):
            messages.put(line.rstrip())
        stream.close()

    def dump_database(
        self,
        database: DatabaseInfo,
        destination: Path,
        application_name: str,
        progress: Progress,
        database_task: int,
        overall_task: int,
        overall_total: int,
        completed_before: int,
        backup_root: Path,
    ) -> DatabaseBackupResult:
        tracker = DumpProgressTracker(database)
        messages: queue.Queue[str] = queue.Queue()
        recent_errors: deque[str] = deque(maxlen=40)
        command = self.client.database_dump_command(database.name, destination)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self.client.environment(application_name),
                start_new_session=True,
            )
        except OSError as exc:
            raise BackupError(f"failed to run pg_dump: {sanitize_text(str(exc), self.client.secrets)}") from exc
        self.active_process = process
        reader = threading.Thread(target=self.stderr_reader, args=(process.stderr, messages), daemon=True)
        reader.start()
        monitor_available = True
        last_monitor = 0.0
        last_size_check = 0.0
        current_size = 0
        current_message = "preparing schema"
        completed = 0
        current_total_size = 0

        try:
            while process.poll() is None:
                while True:
                    try:
                        message = messages.get_nowait()
                    except queue.Empty:
                        break
                    recent_errors.append(message)
                    current_message = message.removeprefix("pg_dump: ")[-100:]

                now = time.monotonic()
                if monitor_available and now - last_monitor >= 1:
                    try:
                        active = self.client.copy_progress(database.name, application_name)
                    except BackupError:
                        monitor_available = False
                    else:
                        completed, active_names = tracker.update(active)
                        if active_names:
                            current_message = ", ".join(active_names[:2])
                            if len(active_names) > 2:
                                current_message += f" +{len(active_names) - 2}"
                    finally:
                        last_monitor = now

                if now - last_size_check >= 2:
                    current_size = directory_size(destination)
                    current_total_size = directory_size(backup_root)
                    last_size_check = now

                percentage = completed / database.progress_weight * 100
                progress.update(
                    database_task,
                    completed=completed,
                    current=escape(current_message),
                    written=human_size(current_size),
                    estimate=f"~{percentage:5.1f}%",
                )
                progress.update(
                    overall_task,
                    completed=completed_before + completed,
                    current=f"database {escape(database.name)}",
                    written=human_size(current_total_size),
                    estimate=f"~{(completed_before + completed) / overall_total * 100:5.1f}%",
                )
                time.sleep(0.2)

            reader.join(timeout=5)
            while True:
                try:
                    message = messages.get_nowait()
                except queue.Empty:
                    break
                recent_errors.append(message)
        except BaseException:
            self.terminate_active_process()
            raise
        finally:
            self.active_process = None

        if process.returncode:
            stderr = "\n".join(recent_errors)
            raise BackupError(f"pg_dump failed for {database.name}: {error_tail(stderr, self.client.secrets)}")

        archive_size = directory_size(destination)
        duration = time.monotonic() - started
        progress.update(
            database_task,
            completed=database.progress_weight,
            current="complete",
            written=human_size(archive_size),
            estimate="100.0%",
        )
        progress.update(
            overall_task,
            completed=completed_before + database.progress_weight,
            current=f"completed {escape(database.name)}",
            written=human_size(directory_size(backup_root)),
            estimate=f"~{(completed_before + database.progress_weight) / overall_total * 100:5.1f}%",
        )
        return DatabaseBackupResult(database, destination, archive_size, duration)

    def dump_databases(self, databases: Sequence[DatabaseInfo], destination: Path) -> list[DatabaseBackupResult]:
        self.print_step(3, "Dump every database")
        total_weight = sum(database.progress_weight for database in databases)
        completed_before = 0
        results = []
        run_token = timestamp_name(self.started_at).lower()
        progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.fields[estimate]:>7}"),
            TextColumn("{task.fields[current]}", justify="left"),
            TextColumn("{task.fields[written]:>10}"),
            TimeElapsedColumn(),
            TextColumn("ETA ~"),
            TimeRemainingColumn(),
            console=self.console,
            expand=True,
        )
        with progress:
            overall_task = progress.add_task(
                "[bold]Overall[/bold]",
                total=total_weight,
                estimate="~0.0%",
                current="starting",
                written="0 B",
            )
            for index, database in enumerate(databases, start=1):
                database_task = progress.add_task(
                    f"[cyan]{escape(database.name)}[/cyan]",
                    total=database.progress_weight,
                    estimate="~0.0%",
                    current="waiting",
                    written="0 B",
                )
                application_name = f"clist-backup-{run_token[-16:]}-{index}"
                result = self.dump_database(
                    database,
                    destination / database.archive_name,
                    application_name,
                    progress,
                    database_task,
                    overall_task,
                    total_weight,
                    completed_before,
                    destination.parent,
                )
                results.append(result)
                completed_before += database.progress_weight
        return results

    def verify_and_finalize_metadata(
        self,
        temporary_root: Path,
        final_name: str,
        results: Sequence[DatabaseBackupResult],
    ) -> None:
        self.print_step(4, "Verify archives and write checksums")
        for result in results:
            with self.console.status(f"Checking {escape(result.database.name)} with pg_restore --list…"):
                self.client.verify_archive(result.archive_path)
            self.console.print(f"[green]✓[/green] {escape(result.database.name)} archive is readable")

        completed_at = utc_now()
        manifest = {
            "format_version": 1,
            "status": "complete",
            "backup_name": final_name,
            "started_at": isoformat_utc(self.started_at),
            "completed_at": isoformat_utc(completed_at),
            "postgres_server_version": self.server_version,
            "pg_dump_major_version": self.client_major,
            "jobs": self.config.jobs,
            "compression": self.config.compression,
            "databases": [
                {
                    "name": result.database.name,
                    "oid": result.database.oid,
                    "archive": result.archive_path.relative_to(temporary_root).as_posix(),
                    "physical_size_bytes": result.database.size_bytes,
                    "estimated_dump_data_bytes": result.database.progress_weight,
                    "archive_size_bytes": result.archive_size_bytes,
                    "table_count": len(result.database.tables),
                    "duration_seconds": round(result.duration_seconds, 3),
                }
                for result in results
            ],
        }
        manifest_path = temporary_root / "manifest.json"
        with manifest_path.open("x", encoding="utf-8") as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
        manifest_path.chmod(0o600)

        files = archive_files(temporary_root)
        checksum_bytes = sum(path.stat().st_size for path in files)
        progress = Progress(
            SpinnerColumn(),
            TextColumn("SHA-256"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("{task.fields[processed]}", justify="right"),
            TimeElapsedColumn(),
            TextColumn("ETA"),
            TimeRemainingColumn(),
            console=self.console,
            expand=True,
        )
        with progress:
            task = progress.add_task("SHA-256", total=max(checksum_bytes, 1), processed="0 B")
            processed = 0

            def on_bytes(value: int) -> None:
                nonlocal processed
                processed += value
                progress.update(task, completed=processed, processed=human_size(processed))

            write_checksums(temporary_root, on_bytes)
            progress.update(task, completed=max(checksum_bytes, 1), processed=human_size(processed))

    def rotation_candidates(self, now: datetime | None = None) -> list[Path]:
        return expired_backup_directories(
            self.config.root,
            now=now or utc_now(),
            retention_days=self.config.retention_days,
        )

    def rotate_backups(self) -> None:
        self.print_step(5, "Apply backup retention")
        candidates = self.rotation_candidates()
        if self.config.retention_days == 0:
            self.console.print("Retention is disabled; no old backups were removed.")
            return
        if not candidates:
            self.console.print(f"No verified backups older than {self.config.retention_days} days.")
            return

        removed_size = 0
        removed_count = 0
        for candidate in candidates:
            size = directory_size(candidate)
            try:
                shutil.rmtree(candidate)
            except OSError as exc:
                self.console.print(f"[yellow]Warning:[/yellow] could not remove {candidate.name}: {escape(str(exc))}")
                continue
            removed_size += size
            removed_count += 1
            self.console.print(f"[green]✓[/green] removed {candidate.name} ({human_size(size)})")
        self.console.print(f"Removed {removed_count} backup(s), reclaimed {human_size(removed_size)}.")

    def show_dry_run(self, databases: Sequence[DatabaseInfo]) -> None:
        self.console.print(
            "\n[bold yellow]Dry run:[/bold yellow] no dump files will be created and nothing will be removed."
        )
        self.console.print(
            f"Would dump {len(databases)} database(s) with {self.config.jobs} worker(s), "
            f"compression level {self.config.compression}."
        )
        candidates = self.rotation_candidates()
        if candidates:
            self.console.print("Would remove after a successful backup:")
            for candidate in candidates:
                self.console.print(f"  • {candidate.name}")
        else:
            self.console.print("No completed backups currently match the retention policy.")

    def run(self) -> Path | None:
        if self.config.root.is_symlink():
            raise BackupError(f"backup root must not be a symlink: {self.config.root}")
        self.config.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config.root.chmod(0o700)
        if not self.config.root.is_dir():
            raise BackupError(f"backup root is not a directory: {self.config.root}")

        self.console.print("[bold blue]CLIST PostgreSQL backup[/bold blue]")
        self.console.print(f"Host output: [bold]{escape(str(self.display_root))}[/bold]")
        with backup_lock(self.config.root):
            databases = self.preflight()
            if self.config.dry_run:
                self.show_dry_run(databases)
                return None

            stamp = timestamp_name(self.started_at)
            final_name = f"postgresql-{stamp}"
            final_root = self.config.root / final_name
            temporary_root = self.config.root / f".{final_name}.in-progress"
            if final_root.exists() or temporary_root.exists():
                raise BackupError(f"backup path already exists for timestamp {stamp}; wait one second and retry")

            temporary_root.mkdir(mode=0o700)
            (temporary_root / "databases").mkdir(mode=0o700)
            try:
                self.dump_globals(temporary_root / "globals.sql")
                results = self.dump_databases(databases, temporary_root / "databases")
                self.verify_and_finalize_metadata(temporary_root, final_name, results)
                temporary_root.rename(final_root)
            except BaseException:
                self.terminate_active_process()
                if temporary_root.exists():
                    try:
                        removed = remove_in_progress(temporary_root, self.config.root)
                    except OSError as exc:
                        removed = False
                        self.console.print(
                            f"[yellow]Warning:[/yellow] failed to remove incomplete backup: {escape(str(exc))}"
                        )
                    if not removed:
                        self.console.print(
                            f"[yellow]Warning:[/yellow] could not safely remove incomplete backup {temporary_root}"
                        )
                raise

            self.rotate_backups()
            final_size = directory_size(final_root)
            display_path = self.display_root / final_name
            self.console.print(
                f"\n[bold green]Backup complete:[/bold green] {escape(str(display_path))} ({human_size(final_size)})"
            )
            return final_root


@contextlib.contextmanager
def translated_signals() -> Iterator[None]:
    previous_handlers: dict[signal.Signals, Any] = {}

    def interrupt(signum: int, _frame: Any) -> None:
        raise BackupInterrupted(f"backup interrupted by {signal.Signals(signum).name}")

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupt)
    try:
        yield
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)
    console = Console()
    error_console = Console(stderr=True)
    try:
        args = build_parser().parse_args(argv)
        config = config_from_args(args)
        application = BackupApplication(config, console)
        with translated_signals():
            application.run()
    except BackupInterrupted as exc:
        error_console.print(f"[bold yellow]{escape(str(exc))}[/bold yellow]")
        return 130
    except BackupError as exc:
        error_console.print(f"[bold red]Backup failed:[/bold red] {escape(str(exc))}")
        return 1
    except KeyboardInterrupt:
        error_console.print("[bold yellow]Backup interrupted[/bold yellow]")
        return 130
    except Exception as exc:
        password = os.environ.get("POSTGRES_PASSWORD", "")
        message = sanitize_text(str(exc), [password]) or exc.__class__.__name__
        error_console.print(f"[bold red]Backup failed unexpectedly:[/bold red] {escape(message)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
