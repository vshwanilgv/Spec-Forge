from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline.gates.sandbox import SandboxGuard, SandboxViolation


class TestSandboxGuardAllowedPaths:
    def test_child_path_inside_allowed_dir_passes(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        guard.validate(str(allowed / "module.py"))

    def test_deeply_nested_child_passes(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        guard.validate(str(allowed / "pkg" / "sub" / "file.py"))

    def test_exact_root_path_passes(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        guard.validate(str(allowed))

    def test_second_of_two_allowed_dirs_passes(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        guard = SandboxGuard([str(dir_a), str(dir_b)])
        guard.validate(str(dir_b / "file.py"))

    def test_first_of_two_allowed_dirs_passes(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        guard = SandboxGuard([str(dir_a), str(dir_b)])
        guard.validate(str(dir_a / "file.py"))


class TestSandboxGuardDisallowedPaths:
    def test_sibling_directory_raises(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        sibling = tmp_path / "secret"
        allowed.mkdir()
        sibling.mkdir()
        guard = SandboxGuard([str(allowed)])
        with pytest.raises(SandboxViolation):
            guard.validate(str(sibling / "file.py"))

    def test_parent_directory_raises(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        with pytest.raises(SandboxViolation):
            guard.validate(str(tmp_path / "other.py"))

    def test_completely_unrelated_path_raises(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        with pytest.raises(SandboxViolation):
            guard.validate("/etc/passwd")

    def test_violation_message_contains_path(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        with pytest.raises(SandboxViolation, match="outside allowed"):
            guard.validate("/etc/passwd")


class TestSandboxGuardTraversalPrevention:
    def test_dotdot_traversal_raises(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        traversal = str(allowed / ".." / "etc" / "passwd")
        with pytest.raises(SandboxViolation):
            guard.validate(traversal)

    def test_nested_dotdot_traversal_raises(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        traversal = str(allowed / "sub" / ".." / ".." / "secret")
        with pytest.raises(SandboxViolation):
            guard.validate(traversal)

    def test_traversal_to_parent_of_allowed_root_raises(self, tmp_path: Path) -> None:
        allowed = tmp_path / "src"
        allowed.mkdir()
        guard = SandboxGuard([str(allowed)])
        with pytest.raises(SandboxViolation):
            guard.validate(str(allowed / ".." ))


class TestSandboxGuardPrefixCollision:
    def test_directory_with_shared_prefix_raises(self, tmp_path: Path) -> None:
        # /src should NOT match /src_evil
        allowed = tmp_path / "src"
        evil = tmp_path / "src_evil"
        allowed.mkdir()
        evil.mkdir()
        guard = SandboxGuard([str(allowed)])
        with pytest.raises(SandboxViolation):
            guard.validate(str(evil / "file.py"))

    def test_allowed_name_as_substring_of_disallowed_raises(self, tmp_path: Path) -> None:
        allowed = tmp_path / "app"
        extra = tmp_path / "application"
        allowed.mkdir()
        extra.mkdir()
        guard = SandboxGuard([str(allowed)])
        with pytest.raises(SandboxViolation):
            guard.validate(str(extra / "settings.py"))
