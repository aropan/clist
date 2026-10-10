import gzip
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "test-django.bash"
FIXTURES = Path("src/ranking/tests/fixtures/parsers")
FETCH_COMMAND = 'git lfs pull --include="src/ranking/tests/fixtures/parsers/**"'
PROJECT_CONTAINERS = "ps --all --filter label=com.docker.compose.project=clist-test"
LFS_POINTER = "version https://git-lfs.github.com/spec/v1\noid sha256:{}\nsize 1\n".format("0" * 64)
# Logs every call. `ps` prints DOCKER_PS_OUTPUT, or DOCKER_PS_OUTPUT_AFTER_RUN once `run` was called, and `run`
# exits with DOCKER_RUN_STATUS.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
if [ "$1" = ps ]; then
    output=${DOCKER_PS_OUTPUT:-}
    if grep -q " run " "$DOCKER_LOG"; then
        output=${DOCKER_PS_OUTPUT_AFTER_RUN:-$output}
    fi
    if [ -n "$output" ]; then
        printf "%s\\n" "$output"
    fi
fi
if [[ " $* " == *" run "* ]]; then
    exit "${DOCKER_RUN_STATUS:-0}"
fi
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def write_archive(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(content.encode(), mtime=0))


def run_script(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "src" / "scripts" / "test-django.bash")],
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    if shutil.which("git") is None or subprocess.run(["git", "lfs", "version"], capture_output=True).returncode:
        pytest.skip("git-lfs is not installed")

    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    docker = bin_path / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_LOG", str(tmp_path / "docker.log"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "CLIST Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@clist.invalid")

    repo = tmp_path / "repo"
    script = repo / "src" / "scripts" / "test-django.bash"
    script.parent.mkdir(parents=True)
    shutil.copy(SCRIPT_PATH, script)
    git(repo, "init")
    git(repo, "lfs", "install", "--local")
    (repo / ".gitattributes").write_text(f"{FIXTURES.as_posix()}/** filter=lfs diff=lfs merge=lfs -text\n")
    write_archive(repo / FIXTURES / "example.com" / "1" / "httpcache.json.gz", "first")
    write_archive(repo / FIXTURES / "example.com" / "2" / "httpcache.json.gz", "second")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Add parser fixtures")
    return repo


def docker_calls(repo: Path) -> list[str]:
    log = repo.parent / "docker.log"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return [call.split(" --format ")[0] for call in calls]


def compose_calls(repo: Path, *commands: str) -> list[str]:
    return [f"compose --project-name clist-test -f {repo}/docker-compose.test.yml {command}" for command in commands]


def test_materialized_fixtures_run_the_stack(checkout: Path) -> None:
    result = run_script(checkout)

    assert result.returncode == 0, result.stderr
    down, build, run = compose_calls(checkout, "down --volumes --remove-orphans", "build", "run --rm tests")
    assert docker_calls(checkout) == [PROJECT_CONTAINERS, down, build, run, PROJECT_CONTAINERS, down]


def test_containers_from_the_test_file_are_removed(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_PS_OUTPUT", f"clist-test-db-1\t{checkout}/docker-compose.test.yml")

    result = run_script(checkout)

    assert result.returncode == 0, result.stderr
    assert docker_calls(checkout).count(compose_calls(checkout, "down --volumes --remove-orphans")[0]) == 2


@pytest.mark.parametrize(
    "config_files",
    ["/srv/clist/docker-compose.yml", "{repo}/docker-compose.yml", "{repo}/docker-compose.test.yml,/tmp/extra.yml", ""],
)
def test_foreign_project_container_stops_before_any_change(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, config_files: str
) -> None:
    monkeypatch.setenv(
        "DOCKER_PS_OUTPUT",
        f"clist-test-db-1\t{checkout}/docker-compose.test.yml\nclist-db-1\t{config_files.format(repo=checkout)}",
    )

    result = run_script(checkout)

    assert result.returncode == 1
    assert result.stderr.count("Refusing to remove Compose project clist-test") == 1
    assert "  clist-db-1" in result.stderr
    assert "clist-test-db-1" not in result.stderr
    assert docker_calls(checkout) == [PROJECT_CONTAINERS]


@pytest.mark.parametrize(("run_status", "expected_status"), [(0, 1), (3, 3)])
def test_stack_left_behind_fails_the_run(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, run_status: int, expected_status: int
) -> None:
    monkeypatch.setenv("DOCKER_RUN_STATUS", str(run_status))
    monkeypatch.setenv("DOCKER_PS_OUTPUT_AFTER_RUN", "clist-db-1\t/srv/clist/docker-compose.yml")

    result = run_script(checkout)

    assert result.returncode == expected_status
    assert "Refusing to remove Compose project clist-test" in result.stderr
    down, build, run = compose_calls(checkout, "down --volumes --remove-orphans", "build", "run --rm tests")
    assert docker_calls(checkout) == [PROJECT_CONTAINERS, down, build, run, PROJECT_CONTAINERS]


def test_locally_modified_archive_is_accepted(checkout: Path) -> None:
    write_archive(checkout / FIXTURES / "example.com" / "1" / "httpcache.json.gz", "refreshed")

    result = run_script(checkout)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("change", ["pointer", "missing"])
def test_unfetched_archive_fails_before_docker(checkout: Path, change: str) -> None:
    archive = FIXTURES / "example.com" / "2" / "httpcache.json.gz"
    if change == "pointer":
        (checkout / archive).write_text(LFS_POINTER, encoding="utf-8")
    else:
        (checkout / archive).unlink()

    result = run_script(checkout)

    assert result.returncode == 1
    assert "missing or pointers" in result.stderr
    assert archive.as_posix() in result.stderr
    assert (FIXTURES / "example.com" / "1").as_posix() not in result.stderr
    assert FETCH_COMMAND in result.stderr
    assert docker_calls(checkout) == []


def test_checkout_without_tracked_fixtures_fails(checkout: Path) -> None:
    git(checkout, "rm", "-r", FIXTURES.as_posix())
    git(checkout, "commit", "-m", "Remove parser fixtures")

    result = run_script(checkout)

    assert result.returncode == 1
    assert "No Git LFS parser fixtures are tracked" in result.stderr
    assert docker_calls(checkout) == []
