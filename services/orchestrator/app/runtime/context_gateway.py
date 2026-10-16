"""Model-family context gate. Trusted validation records are service inputs.

This validates references and byte integrity, not translation quality. A
translation/QA service must establish the supplied validation records first.
Missing records block Claude; source text never registers its own authority.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import unicodedata
from types import MappingProxyType


class ContextBlocked(PermissionError):
    pass


@dataclass(frozen=True)
class ProtectedSpan:
    source_start: int
    source_end: int
    view_start: int
    view_end: int

    def __post_init__(self):
        if (not all(type(value) is int for value in (self.source_start, self.source_end, self.view_start, self.view_end))
                or not 0 <= self.source_start < self.source_end or not 0 <= self.view_start < self.view_end):
            raise ValueError("PROTECTED_SPAN_INVALID")


@dataclass(frozen=True)
class ValidatedEnglishView:
    source_ref: str
    source_sha256: str
    view_ref: str
    view_sha256: str
    validation_id: str
    language: str = "en"
    status: str = "validated"
    coverage_passed: bool = False
    protected_spans_passed: bool = False
    numeric_entities_passed: bool = False
    protected_spans: tuple[ProtectedSpan, ...] = ()

    def __post_init__(self):
        spans = tuple(self.protected_spans)
        if any(not isinstance(span, ProtectedSpan) for span in spans):
            raise ValueError("PROTECTED_SPAN_INVALID")
        object.__setattr__(self, "protected_spans", tuple(ProtectedSpan(span.source_start, span.source_end,
            span.view_start, span.view_end) for span in spans))


@dataclass(frozen=True)
class ContextRead:
    source_ref: str
    content_ref: str
    content: bytes
    sha256: str
    language: str
    trust: str = "untrusted_material"


class ContextGateway:
    def __init__(self, workspace, english_views=None):
        self.workspace = workspace
        registered = {}
        for key, value in (english_views or {}).items():
            if not isinstance(value, ValidatedEnglishView):
                raise ContextBlocked("ENGLISH_VIEW_RECORD_INVALID")
            registered[key] = replace(value, protected_spans=tuple(value.protected_spans))
        self.english_views = MappingProxyType(registered)

    def read(self, model_family, relative_path, role="A", english_view=None):
        if model_family not in {"claude", "gpt", "glm"}:
            raise ContextBlocked("MODEL_FAMILY_UNVERIFIED")
        source_path = self.workspace.resolve(relative_path, role)
        source_ref = source_path.relative_to(self.workspace.root).as_posix()
        source = self.workspace.read(role, source_ref)
        source_hash = hashlib.sha256(source).hexdigest()
        if model_family != "claude":
            return ContextRead(source_ref, source_ref, source, source_hash, "native")
        proof = self.english_views.get(source_ref)
        if proof is None or (english_view is not None and english_view != proof):
            raise ContextBlocked("ENGLISH_VIEW_REQUIRED")
        if (not isinstance(proof, ValidatedEnglishView) or proof.source_ref != source_ref
                or proof.status != "validated" or proof.language != "en"
                or not isinstance(proof.validation_id, str) or not proof.validation_id.strip()
                or any(value is not True for value in (proof.coverage_passed,
                    proof.protected_spans_passed, proof.numeric_entities_passed))):
            raise ContextBlocked("ENGLISH_VIEW_VALIDATION_INCOMPLETE")
        if source_hash != proof.source_sha256:
            raise ContextBlocked("ENGLISH_VIEW_SOURCE_CHANGED")
        view_path = self.workspace.resolve(proof.view_ref, role)
        if view_path.relative_to(self.workspace.root).parts[0] != "translation":
            raise ContextBlocked("ENGLISH_VIEW_SCOPE_INVALID")
        view = self.workspace.read(role, proof.view_ref)
        if hashlib.sha256(view).hexdigest() != proof.view_sha256:
            raise ContextBlocked("ENGLISH_VIEW_BYTES_CHANGED")
        try:
            view.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContextBlocked("ENGLISH_VIEW_UTF8_REQUIRED") from exc
        natural = bytearray(view)
        previous_end = 0
        for span in sorted(proof.protected_spans, key=lambda item: item.view_start):
            if (not all(isinstance(value, int) and not isinstance(value, bool) for value in
                    (span.source_start, span.source_end, span.view_start, span.view_end))
                    or not 0 <= span.source_start < span.source_end <= len(source)
                    or not previous_end <= span.view_start < span.view_end <= len(view)
                    or source[span.source_start:span.source_end] != view[span.view_start:span.view_end]):
                raise ContextBlocked("PROTECTED_SPAN_CHANGED")
            natural[span.view_start:span.view_end] = b" " * (span.view_end - span.view_start)
            previous_end = span.view_end
        try:
            text = natural.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContextBlocked("PROTECTED_SPAN_BOUNDARY_INVALID") from exc
        if any(unicodedata.category(character).startswith("L") and
               "LATIN" not in unicodedata.name(character, "") for character in text):
            raise ContextBlocked("NON_ENGLISH_NATURAL_LANGUAGE")
        return ContextRead(source_ref, proof.view_ref, view, proof.view_sha256, "en")
