"""Recompute the fixed sample and validate captured evidence without model calls."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def verify():
    source = read("native-trial-source.json")
    values = source["values"]
    assert values == [1, 2, 3] and all(type(value) is int for value in values)
    computed = {"count": len(values), "sum": sum(values), "mean": sum(values) / len(values)}
    a = read("gpt-native-answer.json")
    b = read("glm-b-answer.json")
    a_report = read("gpt-native-trial.json")
    b_report = read("glm-b-trial.json")
    checks = {
        "A_completed": a_report["exit_code"] == 0 and a_report["turn_completed"],
        "A_capture_hash_matches": digest(HERE / "gpt-native-answer.json") == a_report["answer_sha256"],
        "A_capture_matches_report": a == a_report["answer"],
        "A_values_match_recomputation": all(a.get(key) == value for key, value in computed.items()),
        "A_integer_fields": type(a.get("count")) is int and type(a.get("sum")) is int,
        "B_schema_keys": set(b) == {"role", "checked_values", "count", "sum", "mean", "verification_zh"},
        "B_role_and_values": b.get("role") == "B" and b.get("checked_values") == values,
        "B_integer_fields": type(b.get("count")) is int and type(b.get("sum")) is int,
        "B_numeric_mean": type(b.get("mean")) in (int, float),
        "B_values_match_recomputation": all(b.get(key) == value for key, value in computed.items()),
        "B_capture_hash_matches": digest(HERE / "glm-b-answer.json") == b_report["answer_sha256"],
        "B_capture_matches_report": b == b_report["answer"],
        "B_prompt_hash_matches": digest(HERE / "glm-b-prompt.txt") == b_report["prompt_sha256"],
        "B_UI_completion_observed": b_report["ui_completed_label"] == "已工作 13 秒" and b_report["ui_stop_button_present"] is False,
        "B_provenance_is_UI_capture": b_report["capture_kind"] == "UI text; not provider raw bytes",
        "Production_remains_disabled": a_report["production_enabled"] is False and b_report["production_enabled"] is False,
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checker": str(Path(__file__).resolve()),
        "checker_sha256": digest(Path(__file__).resolve()),
        "source_sha256": digest(HERE / "native-trial-source.json"),
        "a_answer_sha256": digest(HERE / "gpt-native-answer.json"),
        "b_answer_sha256": digest(HERE / "glm-b-answer.json"),
        "checked_values": values,
        "computed": computed,
        "checks": checks,
        "passed": all(checks.values()),
        "scope": "Local deterministic arithmetic and captured-evidence consistency only",
        "model_identity_or_production_integration_verified": False,
        "model_turns_started": 0,
    }
    (HERE / "native-c-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return result["passed"]


if __name__ == "__main__":
    raise SystemExit(0 if verify() else 1)
