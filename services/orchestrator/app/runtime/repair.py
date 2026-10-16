"""Defect progress is measured across revisions, independently of retry costs."""
import copy


class RepairTracker:
    def __init__(self, state=None):
        self.state = copy.deepcopy(state) if state is not None else {}
        for key, value in {"policy_version": "repair-1", "quality_repairs": 0,
            "connection_retries": 0, "translation_retries": 0, "no_progress": 0,
            "defect_streaks": {}, "history": []}.items():
            self.state.setdefault(key, value)

    def observe(self, defects, revision_id, byte_sha256):
        current = set(defects)
        previous = self.state["defect_streaks"]
        self.state["defect_streaks"] = {defect: previous.get(defect, 0) + 1 for defect in sorted(current)}
        self.state["no_progress"] = max(self.state["defect_streaks"].values(), default=0)
        self.state["history"].append({"revision_id": revision_id, "byte_sha256": byte_sha256,
            "unresolved_defects": sorted(current), "no_progress": self.state["no_progress"]})

    def next_action(self):
        if self.state["no_progress"] >= 2 or self.state["quality_repairs"] >= 3:
            return "takeover"
        self.state["quality_repairs"] += 1
        return "repair"

    def connection_failure(self):
        self.state["connection_retries"] += 1
        return self.state["connection_retries"] <= 2

    def translation_failure(self):
        self.state["translation_retries"] += 1
        return self.state["translation_retries"] <= 3

    def snapshot(self):
        return copy.deepcopy(self.state)
