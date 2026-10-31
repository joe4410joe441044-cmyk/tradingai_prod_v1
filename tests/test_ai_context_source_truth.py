from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.context import Availability, read_source_truth
from backend.context import source_truth as source_truth_module
from backend.context.source_truth import READER_NAME


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "one")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "file.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "two")
    second = _git(repo, "rev-parse", "HEAD")
    return repo, first, second


def test_git_head_origin_main_divergence(tmp_path):
    repo, first, second = _init_repo(tmp_path)
    _git(repo, "update-ref", "refs/remotes/origin/main", first)
    truth = read_source_truth(
        repo, observed_at=datetime(2026, 10, 25, tzinfo=timezone.utc)
    )
    assert truth.head == second
    assert truth.originMain == first
    assert truth.ahead == 1
    assert truth.behind == 0
    assert truth.meta.availability is Availability.AVAILABLE
    assert truth.meta.provenance[0].reader == READER_NAME


def test_git_dirty_working_tree(tmp_path):
    repo, _, _ = _init_repo(tmp_path)
    _git(repo, "update-ref", "refs/remotes/origin/main", _git(repo, "rev-parse", "HEAD"))
    clean = read_source_truth(repo)
    assert clean.dirty is False

    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty = read_source_truth(repo)
    assert dirty.dirty is True


def test_unknown_deployed_commit_never_uses_local_head(tmp_path):
    repo, _, second = _init_repo(tmp_path)
    truth = read_source_truth(repo)
    assert truth.head == second
    assert truth.deployedCommit is None
    assert truth.deployedCommitState is Availability.UNKNOWN
    assert truth.deployedCommitEvidence is None


def test_explicit_deployed_commit_is_recorded(tmp_path):
    repo, first, second = _init_repo(tmp_path)
    truth = read_source_truth(repo, deployed_commit=first)
    assert truth.head == second
    assert truth.deployedCommit == first
    assert truth.deployedCommitState is Availability.AVAILABLE
    assert truth.deployedCommitEvidence


def test_invalid_deployed_commit_rejected(tmp_path):
    repo, _, _ = _init_repo(tmp_path)
    with pytest.raises(ValueError):
        read_source_truth(repo, deployed_commit="; rm -rf /")


def test_reader_uses_fixed_argument_vector_without_shell(tmp_path):
    repo, _, _ = _init_repo(tmp_path)
    real_run = subprocess.run
    calls: list[tuple[list[str], dict]] = []

    def recording_run(args, **kwargs):
        calls.append((list(args), kwargs))
        return real_run(args, **kwargs)

    with patch.object(source_truth_module.subprocess, "run", side_effect=recording_run):
        read_source_truth(repo)

    assert calls
    for args, kwargs in calls:
        assert isinstance(args, list)
        assert args[0] == "git"
        assert kwargs["shell"] is False
        assert args[1] == "-C"
        assert str(repo.resolve()) == args[2]


def test_worktrees_are_reported_read_only(tmp_path):
    repo, _, _ = _init_repo(tmp_path)
    truth = read_source_truth(repo)
    assert truth.worktrees
    assert any(Path(item.path).resolve() == repo.resolve() for item in truth.worktrees)
