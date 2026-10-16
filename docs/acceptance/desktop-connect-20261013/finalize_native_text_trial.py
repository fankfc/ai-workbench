"""Verify the existing completed pilot and write a summary; starts no models."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


source = read("native-trial-source.json")
a = read("gpt-native-trial.json")
b = read("glm-b-trial.json")
c = read("native-c-check.json")
r = read("gpt-review-trial.json")
budget = read("native-trial-budget.json")
review = read("gpt-review-answer.json")
hashes = json.loads((ROOT / "docs/acceptance/backend-source-hashes.json").read_text(encoding="utf-8"))["hashes"]
changed = [name for name, expected in hashes.items() if not (ROOT / name).is_file() or sha(ROOT / name) != expected]
checks = {
    "A_actual_completed_text_turn": a["exit_code"] == 0 and a["turn_completed"] and a["text_experiment_passed"],
    "A_answer_bytes_hash_matches": sha(HERE / "gpt-native-answer.json") == a["answer_sha256"] == c["a_answer_sha256"],
    "B_answer_bytes_hash_matches": sha(HERE / "glm-b-answer.json") == b["answer_sha256"] == c["b_answer_sha256"],
    "B_prompt_bytes_hash_matches": sha(HERE / "glm-b-prompt.txt") == b["prompt_sha256"],
    "source_bytes_hash_matches": sha(HERE / "native-trial-source.json") == c["source_sha256"],
    "C_checker_bytes_hash_matches": sha(HERE / "verify_native_text_trial.py") == c["checker_sha256"],
    "C_16_checks_passed": len(c["checks"]) == 16 and all(c["checks"].values()) and c["passed"],
    "C_fixed_source_recomputed": source["values"] == [1, 2, 3] and c["computed"] == {"count": len(source["values"]), "sum": sum(source["values"]), "mean": sum(source["values"]) / len(source["values"])},
    "review_actual_completed": r["exit_code"] == 0 and r["turn_completed"] and r["text_review_passed"],
    "review_answer_bytes_hash_matches": sha(HERE / "gpt-review-answer.json") == r["answer_sha256"] and review == r["answer"],
    "review_b_binding_matches": review["b_answer_sha256"] == r["reviewed_b_answer_sha256"] == sha(HERE / "glm-b-answer.json"),
    "review_c_binding_matches": review["c_evidence_sha256"] == r["reviewed_c_evidence_sha256"] == sha(HERE / "native-c-check.json"),
    "review_arithmetic_PASS": review["verdict"] == "PASS" and (review["count"], review["sum"], review["mean"]) == (3, 6, 2),
    "top_level_submissions_within_budget": budget["first_trial_starts"] == 1 and budget["b_turn_submission_count"] == 1 and budget["a_review_turn_submission_count"] == 1 and budget["total_top_level_turn_submissions"] == budget["maximum_model_turn_starts"] == 3,
    "production_and_original_D020_not_promoted": a["production_enabled"] is False and b["production_enabled"] is False and r["production_enabled"] is False and r["original_D020_acceptance_passed"] is False,
    "frozen_backend_sources_unchanged": not changed,
}
usage_fields = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")
gpt_usage = {field: a["usage"].get(field, 0) + r["usage"].get(field, 0) for field in usage_fields}
summary = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "user_direction": "没有Claude就先拿gpt进行试验",
    "pilot_passed": all(checks.values()),
    "scope": "Actual GPT CLI guidance -> actual ZCode GUI B reply -> deterministic local C -> actual GPT CLI arithmetic review; agent transferred inline text",
    "source": source,
    "result": {"count": 3, "sum": 6, "mean": 2},
    "review_verdict": review["verdict"],
    "review_issues_zh": review["issues_zh"],
    "actual_top_level_model_turn_submissions": 3,
    "actual_GPT_completed_turns": 2,
    "actual_B_completed_UI_replies": 1,
    "provider_internal_or_title_turns": "unknown; GUI title changed automatically",
    "model_selection": {"A": "Existing authenticated Codex CLI, GPT route; exact response model ID unavailable", "B_UI": "GLM-5.3", "actual_response_model_ids_verified": False},
    "GPT_reported_usage": gpt_usage,
    "GPT_total_input_plus_output_tokens": gpt_usage["input_tokens"] + gpt_usage["output_tokens"],
    "reasoning_usage_note": "reasoning_output_tokens is a reported subfield; do not add it again to output_tokens",
    "GLM_billed_usage": None,
    "GLM_context_meter": b["context_meter"],
    "monetary_usage": "unknown",
    "budget_enforcement": "Three submitted top-level pilot turns, no retries. Initial guidance helper is not a durable cross-run budget enforcer; review helper refuses repeats.",
    "configuration_note": "No explicit account/configuration/security setting edits performed by these helpers; account file byte invariance was not independently audited",
    "artifact_origin": {"A": "CLI output-last-message capture", "B": "UI accessibility text capture", "C": "Actual local Python recomputation", "review": "CLI output-last-message capture"},
    "independent_full_B_internal_tool_trace_available": False,
    "frozen_backend_source_count": len(hashes),
    "changed_frozen_backend_sources": changed,
    "production_enabled": False,
    "original_D004_Claude_verified": False,
    "original_D005_headless_ZCode_verified": False,
    "original_D020_acceptance_passed": False,
    "original_part_one_complete": False,
    "original_card_completion": "17/20; unchanged by text pilot",
    "checks": checks,
    "evidence_sha256": {name: sha(HERE / name) for name in (
        "gpt-native-answer.json", "gpt-native-trial.json", "glm-b-answer.json", "glm-b-trial.json",
        "glm-b-prompt.txt", "native-trial-source.json", "native-c-check.json",
        "gpt-review-answer.json", "gpt-review-trial.json", "native-trial-budget.json",
        "verify_native_text_trial.py", "finalize_native_text_trial.py")},
}
(HERE / "gpt-native-pilot-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
markdown = f"""# GPT 替代 Claude 的实际文字试验

记录时间：{summary['generated_at']}。用户指示：没有 Claude 就先拿 GPT 进行试验。

固定样本 1、2、3 的实际试验{'通过' if summary['pilot_passed'] else '未通过'}：条数 **3**、总和 **6**、算术平均数 **2**。GPT 方案、GLM 回复、本地复算和 GPT 最终算术复核一致，复核 verdict 为 **{review['verdict']}**。

| 步骤 | 实际完成与证据 |
| --- | --- |
| A 方案 | 现有登录态的 Codex CLI 完成文字回答；[原始导出](gpt-native-answer.json)、[事件摘要与用量](gpt-native-trial.json) |
| B 执行 | 通过 ZCode 界面提交一次任务，界面选择 GLM-5.3，显示“已工作 13 秒”；[实际回复文本](glm-b-answer.json)、[界面来源记录](glm-b-trial.json)、[提交提示词](glm-b-prompt.txt) |
| C 复算 | 本地 Python 实际复算，16 项数据/捕获一致性检查通过；[检查结果](native-c-check.json)、[检查脚本](verify_native_text_trial.py) |
| A 复核 | Codex CLI 实际回复 PASS，并绑定 B 与 C 的证据哈希；[回复](gpt-review-answer.json)、[完成与用量记录](gpt-review-trial.json) |

代理在 CLI 与 GUI 之间传递内联文本。这轮证明已能通过现有入口完成简单文字试验；尚未通过原后端自动调度链路。B 文件是界面可访问文本的保存，并非供应商原始响应字节。

本轮提交 3 次顶层任务：GPT 2 次完成、GLM 界面 1 次完成，没有自动重试。ZCode 自动改变了任务标题，供应商内部及标题生成调用次数未知。[预算记录](native-trial-budget.json)记录本轮提交；最初方案脚本每次重跑会覆盖计数，不能据此声称持久跨运行预算强制执行。

GPT 两轮报告输入 **{gpt_usage['input_tokens']:,}**、输出 **{gpt_usage['output_tokens']:,}** token，合计 **{summary['GPT_total_input_plus_output_tokens']:,}**；reasoning_output_tokens={gpt_usage['reasoning_output_tokens']} 是报告中的子字段，不另加到输出。GLM 界面上下文占用 24,669/1,000,000 不等于计费用量；GLM 计费用量与本轮金额未知，未声称节省 token。

GPT 复核指出 B 的“人工推算”措辞不成立：B 是模型，其原回复保持原样作为证据，面向用户的结论采用“模型核验与本地复算”。没有完整 B 内部工具轨迹，模型自述“未运行命令/未联网”不能作为独立证明。GPT 与 GLM 的实际响应 model_id 均未独立验证，GLM-5.3 仅为实际观察到的界面选择。

没有启用生产提供方。Claude 接入、ZCode 无界面执行/取消/恢复、真实身份以及原 D020 正式集成仍未通过。部分一卡片维持 **17/20**。冻结后端源码与依赖锁 **{len(hashes)}** 份哈希{'全部一致' if not changed else '存在变化'}；此前 780 项本地回归属于既有记录，本轮未重复运行后端测试。

本轮最后的只读一致性检查 {sum(checks.values())}/{len(checks)} 项通过，未启动新模型。[结构化总报告](gpt-native-pilot-report.json)、[最终核验脚本](finalize_native_text_trial.py)。
"""
(HERE / "gpt-native-pilot-report.md").write_text(markdown, encoding="utf-8")
print(json.dumps({"pilot_passed": summary["pilot_passed"], "checks_passed": sum(checks.values()), "check_count": len(checks), "frozen_source_count": len(hashes), "changed_frozen_sources": changed, "GPT_reported_usage": gpt_usage, "top_level_submissions": 3, "production_enabled": False, "original_D020_acceptance_passed": False}, ensure_ascii=True))
raise SystemExit(0 if summary["pilot_passed"] else 1)
