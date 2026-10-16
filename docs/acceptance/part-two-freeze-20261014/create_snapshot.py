"""Freeze unfinished phase-two work without changing implementation or Git history."""

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import runpy
import zipfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PREFIX = HERE.relative_to(ROOT).as_posix()
PLAN = ROOT / "docs/superpowers/plans/2026-10-13-execution"
PART_TWO = ROOT / "docs/acceptance/part-two"
FIRST_FREEZE = ROOT / "docs/acceptance/part-one-freeze-20261014"
FREEZE_PATH = f"{PREFIX}/freeze.json"
CARD_IDS = [f"D{number:03}" for number in range(21, 41)]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_sha(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def files_below(folder):
    return sorted(path for path in folder.rglob("*") if path.is_file())


def prepend_note(path, note):
    original = path.read_text(encoding="utf-8-sig")
    assert "阶段二冻结更新：" not in original, f"Already marked: {path}"
    heading, rest = original.split("\n", 1)
    path.write_text(f"{heading}\n\n{note}\n{rest}", encoding="utf-8")


def main():
    assert not (HERE / "freeze.json").exists(), "Existing freeze must not be overwritten"
    assert (HERE / "verify_snapshot.py").is_file(), "Independent verifier is required"
    source_reference = PART_TWO / "final-source-after.json"
    source = read_json(source_reference)
    source_api = runpy.run_path(str(ROOT / "scripts/phase_two_manifest.py"))
    current_source = {
        path.relative_to(ROOT).as_posix(): sha(path.read_bytes())
        for path in source_api["source_files"]("all")
    }
    assert current_source == source["files"], "Implementation differs from final test source"
    assert sha(json.dumps(current_source, sort_keys=True).encode()) == source["source_sha256"]

    board = read_json(PLAN / "task-board.json")
    data = read_json(PLAN / "data/tasks-02.json")
    results = read_json(PART_TWO / "task-results.json")
    verification = read_json(PART_TWO / "verification.json")
    cards = [card for card in board["tasks"] if card["id"] in CARD_IDS]
    assert [card["id"] for card in cards] == CARD_IDS
    assert Counter(card["status"] for card in cards) == {"in_progress": 18, "blocked": 2}
    assert [card["id"] for card in cards if card["status"] == "blocked"] == ["D024", "D040"]
    assert {card["id"]: card["status"] for card in data} == {
        card["id"]: card["status"] for card in cards
    }
    assert {card["id"]: card["status"] for card in results["cards"]} == {
        card["id"]: card["status"] for card in cards
    }
    assert verification["real_model_calls"] == results["real_model_calls"] == 0
    assert verification["complete"] is False

    preserved = {
        "first_part_files": {
            path.relative_to(ROOT).as_posix(): sha(path.read_bytes())
            for path in files_below(FIRST_FREEZE)
        },
        "task_groups": {
            "part_one": canonical_sha(board["tasks"][:20]),
            "future": canonical_sha(board["tasks"][40:]),
        },
        "first_part_execution_summary": canonical_sha(board["execution_summary"]),
        "historical_verification_sha256": sha((PART_TWO / "verification.json").read_bytes()),
    }
    frozen_at = datetime.now().astimezone().isoformat()
    marker = {"status": "frozen_partial", "frozen_at": frozen_at, "evidence": FREEZE_PATH}
    for card in cards:
        card["freeze"] = dict(marker)
    for card in data:
        card["freeze"] = dict(marker)
    for card in results["cards"]:
        card["freeze"] = dict(marker)
    results["freeze"] = dict(marker)
    board["development_status"] = "part_two_frozen_partial"
    board["updated_at"] = frozen_at
    board["part_two_execution"].update({
        "updated_at": frozen_at,
        "freeze_state": "frozen_partial",
        "frozen_at": frozen_at,
        "freeze_record": FREEZE_PATH,
        "work_paused": True,
    })
    write_json(PLAN / "task-board.json", board)
    write_json(PLAN / "data/tasks-02.json", data)
    write_json(PART_TWO / "task-results.json", results)
    write_json(HERE / "preserved-state.json", preserved)
    write_json(HERE / "unfinished-tasks.json", {
        "frozen_at": frozen_at,
        "scope": "D021-D040",
        "complete": False,
        "counts": {"in_progress": 18, "blocked": 2, "done": 0},
        "cards": cards,
    })

    prepend_note(ROOT / "docs/acceptance/part-two-progress.md",
        "阶段二冻结更新：按用户指令冻结 D021–D040 的未验收部分，暂停继续开发。"
        "18 in_progress、D024/D040 blocked 保持原状态；源码、依赖、逐卡遗留及验证记录已归档。"
        "见[冻结说明](part-two-freeze-20261014/FREEZE.md)。以下测试结果属于冻结前已执行批次。")
    prepend_note(PLAN / "TASK-INDEX.md",
        "阶段二冻结更新：D021–D040 未完成部分已冻结，等待新的继续指令；18 in_progress、"
        "D024/D040 blocked 的验收状态不变。第一部分及 D041–D060 原样保留。"
        "见[冻结说明](../../../acceptance/part-two-freeze-20261014/FREEZE.md)。")
    prepend_note(PLAN / "02-ui-translation-documents.md",
        "阶段二冻结更新：当前未完成的验收与开发已暂停，"
        "恢复入口为[冻结说明](../../../acceptance/part-two-freeze-20261014/FREEZE.md)。"
        "下文原计划和历史测试结果保留，不能据此自行继续执行或改变完成资格。")
    prepend_note(ROOT / "README.md",
        "阶段二冻结更新：未完成的 D021–D040 已冻结并暂停推进，"
        "逐卡遗留、源码与证据快照见[冻结说明](docs/acceptance/part-two-freeze-20261014/FREEZE.md)。")
    with (PART_TWO / "execution-ledger.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n## 未完成部分冻结（{frozen_at}）\n\n"
            "按用户‘冻结未完成的部分’及‘重试’指令，固化 D021–D040 当前实现、依赖与遗留，"
            "暂停继续开发。18 in_progress、D024/D040 blocked 状态保留；第一部分冻结文件、"
            "首20卡与其 execution_summary、D041–D060 未改动。未新增模型调用或 Git 提交。"
            f"恢复记录：{FREEZE_PATH}；源码及证据逐件 SHA-256 与 ZIP 由独立工具校验。\n")

    first_record = read_json(FIRST_FREEZE / "freeze.json")
    state = {
        "schema_version": "1.0",
        "frozen_at": frozen_at,
        "timezone": "Asia/Shanghai",
        "status": "frozen_partial",
        "scope": "D021-D040",
        "user_instruction": "冻结未完成的部分；重试",
        "work_paused": True,
        "complete": False,
        "production_enabled": False,
        "real_model_calls_during_phase_two": 0,
        "new_real_model_calls_during_freeze": 0,
        "commit": None,
        "branch": "codex/part1-foundation",
        "card_status_counts": {"in_progress": 18, "blocked": 2, "done": 0},
        "frozen_cards": CARD_IDS,
        "upstream_blockers": first_record["deferred_cards"],
        "additional_upstream_blocker": "GPT 当前 22 项限制及生命周期资格仍未完成。",
        "first_part_freeze_preserved": True,
        "future_tasks_preserved": "D041-D060 remain planned",
        "historical_local_test_results": verification,
        "tests_rerun_during_freeze": False,
        "quality_equivalence_claim": False,
        "token_savings_claim": False,
        "source_reference": {
            "path": source_reference.relative_to(ROOT).as_posix(),
            "sha256": source["source_sha256"],
            "file_count": len(source["files"]),
        },
        "preserved_state": "preserved-state.json",
        "unfinished_tasks": "unfinished-tasks.json",
        "archive_manifest": "archive-manifest.json",
        "archive_scope": "当前源码、测试、构建配置/锁文件、规格/计划、运行手册与选定冻结/验收证据。",
        "excluded": [".git", ".venv", "node_modules", "dist", "dist-test", ".env",
                     "用户数据目录", "生成的演示/测试数据库", "安装工具与凭据"],
        "restore_policy": "先校验 ZIP 与逐文件哈希；恢复到新目录，按锁文件重建环境。"
                          "等待用户继续指令后推进遗留项，不覆盖当前工作区或第一部分冻结。",
        "resume_order": [
            "核对本冻结记录、ZIP、源码与证据哈希，确认逐卡剩余项。",
            "补齐 D004/D005/D020 与 GPT 当前运行资格，并核验实际模型身份/回执/用量。",
            "完成双语金标准和领域人工评审、Windows 输入法/无障碍及故障矩阵。",
            "装配 D040 完整真实附件/产物/取消/重启断言并执行真实四域验收。",
            "按原卡全部门槛复核后更新状态，保留本冻结历史。",
        ],
    }
    write_json(HERE / "snapshot-state.json", state)
    rows = ["# 阶段二未完成部分冻结", "", f"冻结时间：{frozen_at}（Asia/Shanghai）。", "",
        "按用户指令，**暂停 D021–D040 的未完成开发与验收**。当前实现保留，可从本快照恢复。",
        "18 张卡保持 in_progress，D024、D040 保持 blocked，0 张 done；冻结是工作状态，"
        "不能当作验收通过。D041–D060 保持 planned，第一部分原冻结记录不变。", "",
        "冻结前最后本地证据为 Python 1318 通过、桌面 27 单元和 28 Electron 测试通过；"
        "本次冻结只校验快照及这些历史证据，没有重跑产品测试。真实模型调用 0，生产配置/注册 0。"
        "真实连接、双语/领域人评及完整 D040 真实链路未完成，不能据局部回归开放生产或主张质量/token收益。", "",
        "## 逐卡遗留", "", "| 卡片 | 验收状态 | 未完成部分 |", "| --- | --- | --- |"]
    details = {card["id"]: card for card in results["cards"]}
    for card in cards:
        rows.append(f"| {card['id']} | {card['status']} | {details[card['id']]['remaining']} |")
    rows.extend(["", "每卡已实现内容、依赖和证据完整保存在 [unfinished-tasks.json](unfinished-tasks.json)。",
        "上游 D004/D005/D020 引用[第一部分原冻结](../part-one-freeze-20261014/FREEZE.md)；"
        "GPT 当前生命周期资格仍待补齐。第一部分历史失败记录保持原样，不用后续通过结果改写它。", "",
        "## 快照与恢复", "", "- [源码与证据 ZIP](part-two-unfinished-snapshot.zip)："
        "包含源码、测试、桌面构建配置、依赖锁、规格/计划、运行手册及选定验收证据。",
        "- [冻结元数据](freeze.json)、[逐文件哈希](archive-manifest.json)与"
        "[冻结校验](verification.json)：核对 ZIP、本地字节、源码身份和任务状态。",
        "- [原状态保护记录](preserved-state.json)：第一部分所有冻结文件、首20卡、"
        "其历史 execution_summary 和未来20卡的原哈希。", "",
        "当前 checkout 是无初始提交的 codex/part1-foundation。本次没有 commit、reset、clean 或移走文件。"
        "快照不含环境凭据、用户数据库、node_modules、虚拟环境或安装工具，依赖按锁文件重建。", "",
        "收到用户继续指令后，先运行：", "", "```powershell",
        "& services/orchestrator/.venv/Scripts/python.exe docs/acceptance/part-two-freeze-20261014/verify_snapshot.py",
        "```", "", "若需恢复，先将 ZIP 解压到新的空目录，保留 freeze.json 和验证记录作为旁证，"
        "再按 [开发手册](../../runbooks/development.md) 重建环境。源码若已合法演进，"
        "校验会报告与冻结不同；应保留两个版本，逐件比较后继续，不能覆盖本冻结。", "",
        "解冻顺序：补齐真实运行资格 → 双语/领域人评与 Windows 故障矩阵 → "
        "D040 完整真实四域链路 → 按每卡原门槛更新状态。"])
    (HERE / "FREEZE.md").write_text("\n".join(rows) + "\n", encoding="utf-8")

    selected = {ROOT / name for name in source["files"]}
    for name in (".gitignore", "DESIGN.md", "README.md", "apps/desktop/package.json",
                 "apps/desktop/build.mjs", "apps/desktop/vite.config.ts", "apps/desktop/tsconfig.json",
                 "apps/desktop/playwright.real.config.ts", "docs/acceptance/part-two-progress.md",
                 "docs/acceptance/vertical-report.md", "docs/acceptance/vertical-scenarios.json",
                 "artifacts/acceptance/independent-desktop-review/revalidation.json",
                 "artifacts/acceptance/independent-desktop-review/reproduction.json"):
        selected.add(ROOT / name)
    text_suffixes = {".md", ".json", ".log", ".xml", ".txt", ".yaml", ".toml"}
    for folder in ("docs/superpowers", "docs/decisions", "docs/runbooks", "prompts"):
        selected.update(path for path in files_below(ROOT / folder) if path.suffix in text_suffixes)
    selected.update(path for path in PART_TWO.iterdir() if path.is_file() and path.suffix in text_suffixes)
    selected.update(path for path in files_below(FIRST_FREEZE) if path.suffix != ".zip")
    selected.update(HERE / name for name in (
        "create_snapshot.py", "verify_snapshot.py", "FREEZE.md", "snapshot-state.json",
        "preserved-state.json", "unfinished-tasks.json"))

    manifest = {"schema_version": "1.0", "frozen_at": frozen_at, "files": {}}
    blocked_parts = {".git", ".venv", "node_modules", "__pycache__", "dist", "dist-test"}
    for path in sorted(selected):
        relative = path.relative_to(ROOT)
        assert path.resolve().is_relative_to(ROOT.resolve())
        assert not path.is_symlink() and not blocked_parts.intersection(relative.parts)
        assert path.is_file() and path.name != ".env" and path.suffix != ".sqlite3"
        payload = path.read_bytes()
        manifest["files"][relative.as_posix()] = {"sha256": sha(payload), "bytes": len(payload)}
    manifest_path = HERE / "archive-manifest.json"
    write_json(manifest_path, manifest)
    archive_path = HERE / "part-two-unfinished-snapshot.zip"
    assert not archive_path.exists()
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in manifest["files"]:
            archive.write(ROOT / name, name)
        archive.write(manifest_path, manifest_path.relative_to(ROOT).as_posix())
    state["archive"] = {
        "path": archive_path.relative_to(ROOT).as_posix(),
        "sha256": sha(archive_path.read_bytes()),
        "bytes": archive_path.stat().st_size,
        "payload_file_count": len(manifest["files"]),
        "zip_member_count": len(manifest["files"]) + 1,
    }
    write_json(HERE / "freeze.json", state)
    print(json.dumps({"status": "SNAPSHOT_CREATED_VERIFICATION_PENDING", "frozen_at": frozen_at,
        "cards": len(cards), "archive_files": len(manifest["files"]),
        "archive_bytes": state["archive"]["bytes"], "source_unchanged": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
