"""Explicit immutable revision dependencies and selective DAG invalidation."""
from __future__ import annotations

from copy import deepcopy
from typing import Mapping


class DependencyGraph:
    def __init__(self, value: dict | None = None):
        value = deepcopy(value) if value is not None else {"version": 0, "nodes": {}}
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] < 0 or not isinstance(value.get("nodes"), dict):
            raise ValueError("DEPENDENCY_GRAPH_INVALID")
        self.version = value["version"]
        self.nodes = value["nodes"]
        for logical, node in self.nodes.items():
            if not isinstance(logical, str) or not logical or not isinstance(node, dict) or not isinstance(node.get("revision_id"), str) or not node["revision_id"] or not isinstance(node.get("dependencies"), dict) or type(node.get("stale")) is not bool:
                raise ValueError("DEPENDENCY_GRAPH_INVALID")
            if any(not isinstance(key, str) or not key or not isinstance(revision, str) or not revision for key, revision in node["dependencies"].items()):
                raise ValueError("DEPENDENCY_GRAPH_INVALID")
        self._require_dag(self.nodes)

    @staticmethod
    def _require_dag(nodes):
        visiting, visited = set(), set()
        def visit(key):
            if key in visiting:
                raise ValueError("DEPENDENCY_CYCLE:" + key)
            if key in visited:
                return
            if key not in nodes:
                raise ValueError("DEPENDENCY_NODE_MISSING:" + key)
            visiting.add(key)
            for upstream in nodes[key]["dependencies"]:
                if upstream == key:
                    raise ValueError("DEPENDENCY_SELF_REFERENCE:" + key)
                visit(upstream)
            visiting.remove(key)
            visited.add(key)
        for key in nodes:
            visit(key)

    def to_dict(self):
        return {"version": self.version, "nodes": deepcopy(self.nodes)}

    def register(self, logical_id: str, revision_id: str, dependencies: Mapping[str, str]):
        if not isinstance(logical_id, str) or not logical_id or not isinstance(revision_id, str) or not revision_id or not isinstance(dependencies, Mapping):
            raise ValueError("DEPENDENCY_BINDING_INVALID")
        dependencies = dict(dependencies)
        if logical_id in dependencies:
            raise ValueError("DEPENDENCY_SELF_REFERENCE:" + logical_id)
        if any(not isinstance(key, str) or not key or not isinstance(value, str) or not value for key, value in dependencies.items()):
            raise ValueError("DEPENDENCY_BINDING_INVALID")
        for key, version in dependencies.items():
            if key not in self.nodes or self.nodes[key]["revision_id"] != version or not self.is_current(version):
                raise ValueError("DEPENDENCY_VERSION_NOT_CURRENT:" + key)
        previous = self.nodes.get(logical_id)
        if any(key != logical_id and node["revision_id"] == revision_id for key,node in self.nodes.items()):
            raise ValueError("REVISION_LOGICAL_ID_CONFLICT")
        if previous is not None and previous["revision_id"] == revision_id and previous["dependencies"] != dependencies:
            raise ValueError("REVISION_BINDING_CHANGED")
        if previous is not None and previous["revision_id"] == revision_id and previous["dependencies"] == dependencies and not previous["stale"]:
            return ()
        candidate = deepcopy(self.nodes)
        candidate[logical_id] = {"revision_id": revision_id, "dependencies": dependencies, "stale": False}
        self._require_dag(candidate)
        descendants, frontier = set(), [logical_id]
        while frontier:
            upstream = frontier.pop()
            for key, node in candidate.items():
                if upstream in node["dependencies"] and key not in descendants:
                    descendants.add(key)
                    frontier.append(key)
        affected = {candidate[key]["revision_id"] for key in descendants}
        if previous is not None:
            affected.add(previous["revision_id"])
        for key in descendants:
            candidate[key]["stale"] = True
        self.nodes = candidate
        self.version += 1
        return tuple(sorted(affected))

    def is_current(self, revision_id: str) -> bool:
        matches = [key for key, node in self.nodes.items() if node["revision_id"] == revision_id]
        if len(matches) != 1:
            return False
        def valid(key):
            node = self.nodes[key]
            return not node["stale"] and all(upstream in self.nodes and self.nodes[upstream]["revision_id"] == version and valid(upstream) for upstream, version in node["dependencies"].items())
        return valid(matches[0])
