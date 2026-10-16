"""Deterministic structural checks consume a separate semantic check report."""
import re
import unicodedata
from app.contracts.translation import SemanticFinding, TranslationQA
from .segments import structure
from .protection import restore,MARKER

CHECK_VERSION='translation-qa:1.0'


def high_impact(segment):
    return bool(re.search(r'\b(?:not|never|must|only|if|unless|may|conclusion)\b|禁止|不得|如果|仅|可能|结论|\d',segment.source,re.I))

def has_english_sentence_copy(source,target):
    source=' '.join(source.split()); target=' '.join(target.split())
    return any(len(re.findall(r'[A-Za-z]+',sentence))>=4 and sentence in target
        for sentence in re.split(r'(?<=[.!?])\s+',source) if sentence.strip())


def evaluate(job_id,candidate,segments,protected,blocks,*,semantic_findings=(),verifier_model=None,complete=True,semantic_complete=False,format='markdown',target_language=None,reject_english_copies=False):
    findings=[]; targets=[]; coverage='pass'; protection='pass'; entities='pass'
    source_ids={s.block_id for s in segments}
    if set(blocks)!=source_ids or not complete:
        coverage='fail'
        findings.append(SemanticFinding(block_id=segments[0].block_id,code='BLOCK_COVERAGE_OR_TRUNCATION',severity='major',message='Candidate does not cover the full source.',source_locator=segments[0].source_locator))
    for segment,block in zip(segments,protected):
        value=blocks.get(segment.block_id,'')
        if not isinstance(value,str) or (segment.source.strip() and not value.strip()):
            coverage='fail'; targets.append(''); continue
        try:
            target=restore(block,value); targets.append(target)
        except ValueError as exc:
            protection='fail'; entities='fail'; targets.append('')
            findings.append(SemanticFinding(block_id=segment.block_id,code='PROTECTED_SPAN_CHANGED',severity='major',message=str(exc),source_locator=segment.source_locator)); continue
        if format=='markdown' and structure(segment.source)!=structure(target):
            coverage='fail'
            findings.append(SemanticFinding(block_id=segment.block_id,code='MARKDOWN_STRUCTURE_CHANGED',severity='major',message='Markdown AST structure differs.',source_locator=segment.source_locator))
        natural=MARKER.sub('',value)
        wrong_english=target_language=='en' and any(unicodedata.category(c).startswith('L') and 'LATIN' not in unicodedata.name(c,'') for c in natural)
        wrong_chinese=target_language in ('zh','zh-CN') and bool(re.search(r'[A-Za-z]',natural)) and not bool(re.search(r'[\u3400-\u9fff]',natural))
        if wrong_english or wrong_chinese:
            findings.append(SemanticFinding(block_id=segment.block_id,code='TARGET_LANGUAGE_MISMATCH',severity='major',message='Unprotected natural language does not match the target language.',source_locator=segment.source_locator))
        if reject_english_copies and has_english_sentence_copy(MARKER.sub(' ',block.text),MARKER.sub(' ',value)):
            findings.append(SemanticFinding(block_id=segment.block_id,code='UNTRANSLATED_ENGLISH_QUESTION',severity='major',message='A complete unprotected English question or sentence was copied into the Chinese clarification.',source_locator=segment.source_locator))
    if not semantic_complete:
        findings.append(SemanticFinding(block_id=segments[0].block_id,code='SEMANTIC_CHECK_INCOMPLETE',severity='major',message='Separate semantic check completion is required.',source_locator=segments[0].source_locator))
    for item in semantic_findings:
        finding=SemanticFinding.model_validate(item)
        if finding.block_id not in source_ids:
            raise ValueError('SEMANTIC_FINDING_SCOPE_INVALID')
        findings.append(finding)
    severity='major' if any(f.severity in ('major','critical') for f in findings) else 'minor' if findings else 'none'
    qa=TranslationQA(id=f'{job_id}:qa:{candidate}',job_id=job_id,candidate_version=str(candidate),coverage_result=coverage,
        protected_span_result=protection,numeric_entity_result=entities,semantic_findings=findings,severity=severity,
        verifier_model=verifier_model,check_version=CHECK_VERSION,evidence_ref=f'translation-candidate:{job_id}:{candidate}')
    ready=coverage==protection==entities=='pass' and severity not in ('major','critical') and semantic_complete
    return qa,tuple(targets),ready
