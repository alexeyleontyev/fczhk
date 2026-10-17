"""Release safety checks use an isolated checkout and a fake Docker executable."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OLD = "ghcr.io/example/club@" + "sha256:" + "a" * 64
NEW = "ghcr.io/example/club@" + "sha256:" + "b" * 64
TAG = "ghcr.io/example/club:" + "c" * 40


@pytest.fixture
def release(tmp_path):
    for directory in ("deploy", "scripts"):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    (tmp_path / ".env").write_text("FCZHK_ENV=test\n")
    local = tmp_path / ".local"
    local.mkdir()
    (local / "release-image").write_text(OLD + "\n")
    (local / "previous-image").write_text(OLD + "\n")
    (local / "previous-revision").write_text("old-revision\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, sys
args = sys.argv[1:]
with open(os.environ["DOCKER_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["image", "inspect"]:
    print(os.environ["NEW_IMAGE"])
elif args[0] == "inspect":
    print(os.environ["OLD_IMAGE"])
elif "ps" in args:
    print("old-container")
elif any("to_regclass" in a for a in args):
    print("alembic_version")
elif any("SELECT version_num" in a for a in args):
    print(os.environ.get("SCHEMA_REVISION", "old-revision"))
elif "pg_dump" in args:
    print("test-dump-content")
elif "pg_restore" in args and "--exit-on-error" in args:
    sys.exit(int(os.environ.get("FAIL_RESTORE", "0")))
elif "run" in args and args[-1] == "migrate":
    sys.exit(int(os.environ.get("FAIL_MIGRATION", "0")))
"""
    )
    docker.chmod(0o755)
    # flock is provided by util-linux on production Linux; emulate its lock on macOS.
    if not shutil.which("flock"):
        flock = binary / "flock"
        flock.write_text(
            f"#!{sys.executable}\nimport fcntl, sys\nfcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        )
        flock.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "FCZHK_IMAGE": OLD,
        "NEW_IMAGE": NEW,
        "OLD_IMAGE": OLD,
        "DOCKER_LOG": str(tmp_path / "docker.jsonl"),
    }

    def run(script, *args, **extra):
        result = subprocess.run(
            ["bash", str(tmp_path / "scripts" / script), *args],
            env={**env, **extra},
            capture_output=True,
            text=True,
            timeout=15,
        )
        log = Path(env["DOCKER_LOG"])
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return tmp_path, run


def test_release_stops_writers_and_verifies_backup_before_migration(release):
    root, run = release
    result, calls = run("deploy.sh", TAG)
    assert result.returncode == 0, result.stderr
    stop = next(i for i, c in enumerate(calls) if "stop" in c)
    restore = next(i for i, c in enumerate(calls) if "pg_restore" in c and "--exit-on-error" in c)
    migrate = next(i for i, c in enumerate(calls) if c[-1] == "migrate")
    serve = next(i for i, c in enumerate(calls) if "up" in c and "--no-deps" in c)
    assert stop < restore < migrate < serve
    assert (root / ".local/release-image").read_text().strip() == NEW
    assert (root / ".local/previous-image").read_text().strip() == OLD


@pytest.mark.parametrize("failure", ["FAIL_MIGRATION", "FAIL_RESTORE"])
def test_failed_release_does_not_start_writers_or_record_success(release, failure):
    root, run = release
    result, calls = run("deploy.sh", TAG, **{failure: "1"})
    assert result.returncode != 0
    assert not any("up" in c and "--no-deps" in c for c in calls)
    if failure == "FAIL_RESTORE":
        assert not any(c[-1] == "migrate" for c in calls)
    assert (root / ".local/release-image").read_text().strip() == OLD


def test_rollback_refuses_changed_schema_before_stopping_or_starting_services(release):
    _, run = release
    result, calls = run("rollback.sh", SCHEMA_REVISION="new-revision")
    assert result.returncode != 0
    assert "Schema changed" in result.stderr
    assert not any("stop" in c or "up" in c for c in calls)


def test_release_rejects_mutable_tag_before_any_docker_operation(release):
    _, run = release
    result, calls = run("deploy.sh", "ghcr.io/example/club:latest")
    assert result.returncode != 0 and calls == []
