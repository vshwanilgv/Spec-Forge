from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock, patch


from pipeline.gates.quality import GateResult, QualityGateRunner

_EXPECTED_TOOLS = {"ruff", "mypy", "pytest", "bandit"}


def _completed_process(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


class TestGateResult:
    def test_is_dataclass_with_required_fields(self) -> None:
        result = GateResult(tool="ruff", passed=True, output="All good")
        assert result.tool == "ruff"
        assert result.passed is True
        assert result.output == "All good"

    def test_field_names_match_spec(self) -> None:
        field_names = {f.name for f in fields(GateResult)}
        assert field_names == {"tool", "passed", "output"}


class TestQualityGateRunnerPassingGates:
    def test_all_tools_pass_when_all_return_zero(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(0)):
            results = runner.run_all()
        assert all(r.passed for r in results)

    def test_run_all_returns_result_for_every_expected_tool(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(0)):
            results = runner.run_all()
        assert {r.tool for r in results} == _EXPECTED_TOOLS

    def test_result_count_matches_tool_count(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(0)):
            results = runner.run_all()
        assert len(results) == len(_EXPECTED_TOOLS)


class TestQualityGateRunnerFailingGates:
    def test_nonzero_returncode_marks_gate_failed(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(1)):
            results = runner.run_all()
        assert all(not r.passed for r in results)

    def test_run_all_still_returns_all_results_on_failure(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(1)):
            results = runner.run_all()
        assert len(results) == len(_EXPECTED_TOOLS)

    def test_mixed_returncodes_produce_correct_pass_flags(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        side_effects = [
            _completed_process(0),
            _completed_process(1),
            _completed_process(0),
            _completed_process(1),
        ]
        with patch("subprocess.run", side_effect=side_effects):
            results = runner.run_all()
        assert [r.passed for r in results] == [True, False, True, False]


class TestQualityGateRunnerOutputCapture:
    def test_stdout_is_included_in_gate_output(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(0, stdout="clean")):
            results = runner.run_all()
        for result in results:
            assert "clean" in result.output

    def test_stderr_is_included_in_gate_output(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(1, stderr="error found")):
            results = runner.run_all()
        for result in results:
            assert "error found" in result.output

    def test_stdout_and_stderr_both_captured(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        proc = _completed_process(1, stdout="stdout part", stderr="stderr part")
        with patch("subprocess.run", return_value=proc):
            results = runner.run_all()
        for result in results:
            assert "stdout part" in result.output
            assert "stderr part" in result.output

    def test_empty_output_does_not_raise(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(0, stdout="", stderr="")):
            results = runner.run_all()
        assert all(isinstance(r.output, str) for r in results)


class TestQualityGateRunnerSubprocessCall:
    def test_subprocess_called_with_correct_cwd(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(0)) as mock_run:
            runner.run_all()
        for c in mock_run.call_args_list:
            assert c.kwargs["cwd"] == str(tmp_path)

    def test_subprocess_called_with_capture_output(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(0)) as mock_run:
            runner.run_all()
        for c in mock_run.call_args_list:
            assert c.kwargs["capture_output"] is True

    def test_subprocess_called_four_times(self, tmp_path: Path) -> None:
        runner = QualityGateRunner(str(tmp_path))
        with patch("subprocess.run", return_value=_completed_process(0)) as mock_run:
            runner.run_all()
        assert mock_run.call_count == 4
