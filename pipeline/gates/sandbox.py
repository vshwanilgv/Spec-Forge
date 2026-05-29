from __future__ import annotations

import os


class SandboxViolation(Exception):
    pass


class SandboxGuard:
    def __init__(self, allowed_dirs: list[str]) -> None:
        self._allowed_roots = [
            os.path.realpath(os.path.abspath(d)) for d in allowed_dirs
        ]

    def validate(self, path: str) -> None:
        resolved = os.path.realpath(os.path.abspath(path))
        for root in self._allowed_roots:
            if resolved.startswith(root + os.sep) or resolved == root:
                return
        raise SandboxViolation(
            f"Path '{path}' resolves to '{resolved}' which is outside allowed directories: "
            f"{self._allowed_roots}"
        )
