from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from pipeline.main import (
    _build_spec_model,
    _compute_hash,
    _detect_format,
    _load_raw,
)

VALID_DATA: dict = {
    "feature_objective": "Implement login",
    "user_story": "As a user I want to log in",
    "business_rules": ["Passwords must be hashed"],
    "acceptance_criteria": ["POST /login returns 200 on valid credentials"],
    "non_functional_requirements": ["P99 < 500ms"],
    "out_of_scope": ["OAuth"],
}


class TestDetectFormat:
    def test_yaml_extension_returns_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "spec.yaml"
        p.touch()
        assert _detect_format(p) == "yaml"

    def test_yml_extension_returns_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "spec.yml"
        p.touch()
        assert _detect_format(p) == "yaml"

    def test_json_extension_returns_json(self, tmp_path: Path) -> None:
        p = tmp_path / "spec.json"
        p.touch()
        assert _detect_format(p) == "json"

    def test_unsupported_extension_exits_with_code_1(self, tmp_path: Path) -> None:
        p = tmp_path / "spec.txt"
        p.touch()
        with pytest.raises(SystemExit) as exc:
            _detect_format(p)
        assert exc.value.code == 1

    def test_unknown_extension_exits_with_code_1(self, tmp_path: Path) -> None:
        p = tmp_path / "spec.toml"
        p.touch()
        with pytest.raises(SystemExit) as exc:
            _detect_format(p)
        assert exc.value.code == 1


class TestComputeHash:
    def test_produces_sha256_hex_digest(self) -> None:
        content = "hello world"
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert _compute_hash(content) == expected

    def test_hash_length_is_64_characters(self) -> None:
        assert len(_compute_hash("any content")) == 64

    def test_identical_content_produces_identical_hash(self) -> None:
        content = "deterministic"
        assert _compute_hash(content) == _compute_hash(content)

    def test_different_content_produces_different_hash(self) -> None:
        assert _compute_hash("content A") != _compute_hash("content B")

    def test_empty_string_produces_valid_hash(self) -> None:
        result = _compute_hash("")
        assert len(result) == 64


class TestBuildSpecModel:
    def test_valid_data_builds_model_correctly(self) -> None:
        raw = yaml.dump(VALID_DATA)
        model = _build_spec_model(VALID_DATA, raw, "yaml")
        assert model.feature_objective == "Implement login"
        assert model.raw_format == "yaml"

    def test_spec_hash_matches_raw_content(self) -> None:
        raw = "raw spec content"
        model = _build_spec_model(VALID_DATA, raw, "yaml")
        assert model.spec_hash == _compute_hash(raw)

    def test_version_contains_timestamp_marker(self) -> None:
        raw = yaml.dump(VALID_DATA)
        model = _build_spec_model(VALID_DATA, raw, "yaml")
        assert "T" in model.version
        assert model.version.endswith("Z")

    def test_missing_feature_objective_exits(self) -> None:
        data = {k: v for k, v in VALID_DATA.items() if k != "feature_objective"}
        with pytest.raises(SystemExit) as exc:
            _build_spec_model(data, "", "yaml")
        assert exc.value.code == 1

    def test_missing_acceptance_criteria_exits(self) -> None:
        data = {k: v for k, v in VALID_DATA.items() if k != "acceptance_criteria"}
        with pytest.raises(SystemExit) as exc:
            _build_spec_model(data, "", "yaml")
        assert exc.value.code == 1

    def test_missing_multiple_fields_exits_and_names_them(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        data = {"feature_objective": "Only this"}
        with pytest.raises(SystemExit):
            _build_spec_model(data, "", "yaml")
        captured = capsys.readouterr()
        assert "user_story" in captured.err

    def test_json_format_stored_on_model(self) -> None:
        raw = json.dumps(VALID_DATA)
        model = _build_spec_model(VALID_DATA, raw, "json")
        assert model.raw_format == "json"

    def test_all_list_fields_preserved(self) -> None:
        raw = yaml.dump(VALID_DATA)
        model = _build_spec_model(VALID_DATA, raw, "yaml")
        assert model.business_rules == ["Passwords must be hashed"]
        assert model.acceptance_criteria == ["POST /login returns 200 on valid credentials"]
        assert model.non_functional_requirements == ["P99 < 500ms"]
        assert model.out_of_scope == ["OAuth"]


class TestLoadRaw:
    def test_yaml_file_returns_raw_string_and_dict(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text(yaml.dump(VALID_DATA), encoding="utf-8")
        raw, data = _load_raw(spec_file)
        assert isinstance(raw, str)
        assert data["feature_objective"] == "Implement login"

    def test_json_file_returns_raw_string_and_dict(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(VALID_DATA), encoding="utf-8")
        raw, data = _load_raw(spec_file)
        assert isinstance(raw, str)
        assert data["user_story"] == "As a user I want to log in"

    def test_markdown_file_exits_with_code_1(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Feature\nSome description", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            _load_raw(spec_file)
        assert exc.value.code == 1

    def test_raw_string_matches_file_contents(self, tmp_path: Path) -> None:
        content = yaml.dump(VALID_DATA)
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text(content, encoding="utf-8")
        raw, _ = _load_raw(spec_file)
        assert raw == content
