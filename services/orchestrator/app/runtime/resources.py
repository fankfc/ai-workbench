"""Budgets enforced before launch and while consuming process output."""
from dataclasses import dataclass, fields
import math
import threading


@dataclass(frozen=True)
class ResourceLimits:
    max_running: int = 4
    max_processes_per_job: int = 8
    max_output_bytes: int = 65536
    max_temp_dirs: int = 4
    max_open_handles: int = 128
    cancel_grace_seconds: float = 0.3
    kill_wait_seconds: float = 5.0

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.endswith("seconds"):
                valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and math.isfinite(value) and value >= 0)
                if field.name == "kill_wait_seconds":
                    valid = valid and value > 0
            else:
                valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
            if not valid:
                raise ValueError(f"INVALID_RESOURCE_LIMIT:{field.name}")


class BoundedOutput:
    """One shared byte budget for stdout/stderr, consumed in fixed-size chunks."""

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.seen = 0
        self._stdout = bytearray()
        self._stderr = bytearray()
        self._lock = threading.Lock()

    def append(self, stream: str, data: bytes) -> bool:
        with self._lock:
            self.seen += len(data)
            remaining = max(0, self.budget - len(self._stdout) - len(self._stderr))
            target = self._stdout if stream == "stdout" else self._stderr
            target.extend(data[:remaining])
            return len(data) > remaining

    def read(self, stream: str) -> bytes:
        with self._lock:
            return bytes(self._stdout if stream == "stdout" else self._stderr)

    def snapshot(self) -> tuple[int, int, bool]:
        with self._lock:
            kept = len(self._stdout) + len(self._stderr)
            return self.seen, kept, self.seen > kept
