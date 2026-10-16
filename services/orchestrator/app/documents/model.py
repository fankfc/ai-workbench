import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.providers import ContractModel


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


class ParseIssue(ContractModel):
    code: str
    source_locator: str
    detail: str


class DocumentBlock(ContractModel):
    block_id: str
    kind: str
    parent_id: str | None
    order: int
    source_locator: str
    source_sha256: str
    content: str
    resource_ids: list[str] = Field(default_factory=list)
    translatable: bool = True
    preservation_reason: str | None = None
    metadata: dict = Field(default_factory=dict)


class DocumentModel(ContractModel):
    schema_version: Literal['1.0'] = '1.0'
    source_version_id: str
    source_bytes_sha256: str
    language: str
    blocks: list[DocumentBlock]
    issues: list[ParseIssue] = Field(default_factory=list)
    resources: dict[str, str] = Field(default_factory=dict)
    translation_evidence: dict = Field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return bool(self.blocks) and not self.issues

    @property
    def content_sha256(self) -> str:
        return digest(json_bytes([{'block_id': b.block_id, 'kind': b.kind, 'content': b.content,
            'resources': b.resource_ids, 'metadata': b.metadata} for b in self.blocks]))

    @model_validator(mode='after')
    def unique_block_ids(self):
        if len({b.block_id for b in self.blocks}) != len(self.blocks):
            raise ValueError('DOCUMENT_BLOCK_ID_DUPLICATE')
        if [b.order for b in self.blocks] != list(range(len(self.blocks))):
            raise ValueError('DOCUMENT_BLOCK_ORDER_INVALID')
        return self


def block(kind, content, locator, order, *, parent_id=None, translatable=True, metadata=None, resources=None):
    return DocumentBlock(block_id=f'b{order:05d}', kind=kind, parent_id=parent_id, order=order,
        source_locator=locator, source_sha256=digest(content.encode('utf-8')), content=content,
        translatable=translatable, preservation_reason=None if translatable else kind,
        metadata=metadata or {}, resource_ids=resources or [])
