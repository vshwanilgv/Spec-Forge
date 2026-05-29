from __future__ import annotations

import os

from pipeline.models import PipelineState

_TMP_SUFFIX = ".tmp"


class StateStore:
    def __init__(self, state_path: str) -> None:
        self._state_path = state_path

    def load(self) -> PipelineState:
        with open(self._state_path, "r", encoding="utf-8") as fh:
            return PipelineState.model_validate_json(fh.read())

    def save(self, state: PipelineState) -> None:
        tmp_path = self._state_path + _TMP_SUFFIX
        payload = state.model_dump_json(indent=2)
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_path, self._state_path)
