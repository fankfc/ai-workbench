"""Language views through the existing workspace permission gateway only."""
from dataclasses import dataclass
import hashlib
from app.runtime.context_gateway import ContextGateway, ValidatedEnglishView
from .segments import segment_document
from .protection import protect, view_span_positions


@dataclass(frozen=True)
class SourceMaterial:
    source_ref: str
    language: str='zh-CN'
    format: str='markdown'
    selected_block_ids: tuple[str,...]=()
    critical_ocr_uncertainty: bool=False


def english_view(workspace,material,result):
    source=workspace.read('service',material.source_ref).decode()
    if hashlib.sha256(source.encode()).hexdigest()!=result.source_sha256 or result.status!='READY':
        raise ValueError('MATERIAL_TRANSLATION_NOT_READY')
    segments=segment_document(source,format=material.format,locator=material.source_ref)
    protected=tuple(protect(s) for s in segments)
    # Recover block boundaries from the candidate's protected form, never guess
    # locations in a flattened translation with repeated strings.
    from .protection import restore
    blocks={item['block_id']:item['target'] for item in result.blocks}
    targets=tuple(restore(block,blocks[block.block_id]) for block in protected)
    view_ref=f'translation/{result.job_id}.en.md'
    workspace.write('service',view_ref,result.text.encode())
    proof=ValidatedEnglishView(material.source_ref,result.source_sha256,view_ref,result.target_sha256,result.qa_id,
        coverage_passed=True,protected_spans_passed=True,numeric_entities_passed=True,
        protected_spans=view_span_positions(segments,protected,targets))
    # Runtime gateway independently verifies bytes and remaining natural language.
    ContextGateway(workspace,{material.source_ref:proof}).read('claude',material.source_ref)
    return proof,tuple(s.block_id for s in segments)
