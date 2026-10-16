"""Exact protected bytes within AST blocks, including placeholder collisions."""
from dataclasses import dataclass, asdict
import hashlib
import re

MARKER=re.compile(r'⟦WB:[^⟧]*⟧')
PATTERNS=(
    ('collision',MARKER),
    ('code',re.compile(r'(`+)(.+?)\1',re.S)),
    ('formula',re.compile(r'\$\$.*?\$\$|(?<!\\)\$[^$\n]+\$|\\\(.*?\\\)|\\\[.*?\\\]',re.S)),
    ('path',re.compile(r'[A-Za-z]:\\[^\s`<>"，。]+|(?<!\w)/(?:[\w.-]+/)+[\w.-]+|(?<![\w/])(?:input|inputs|translation|evidence|a|b)/[^\s`<>"，。]+')),
    ('doi',re.compile(r'\b10\.\d{4,9}/[^\s<>\])，。]+')),
    ('url',re.compile(r'https?://[^\s<>\])]+')),
    ('reference',re.compile(r'\[[0-9]+(?:[-,][0-9]+)*\]|\[[^\]\n]+\]:\s*\S+')),
    ('entity',re.compile(r'\b(?:[A-Z]{2,}|OpenAI|GitHub|Claude|ChatGPT|GPT-\d[^\s]*)\b')),
    ('number',re.compile(r'(?<![\w])(?:(?:<=|>=|[<>≤≥=])\s*)?[-+−]?\d+(?:\.\d+)?(?:\s*%|\s*(?:kg|mg|g|ml|mL|km|ms|cm|mm|s|Hz|kHz|MHz|GB|MB|USD|CNY|°C|mmHg)\b)?')),
)


@dataclass(frozen=True)
class ProtectedSpan:
    id: str
    kind: str
    raw: str
    sha256: str
    start: int
    end: int
    marker: str

    def to_dict(self): return asdict(self)


@dataclass(frozen=True)
class ProtectedBlock:
    block_id: str
    text: str
    spans: tuple[ProtectedSpan,...]


def protect(segment):
    source=segment.source; selected=[]
    if segment.kind in ('fence','code_block','html_block','gap','hr'):
        selected=[(0,len(source),'structure')]
    else:
        for kind,pattern in PATTERNS:
            for match in pattern.finditer(source):
                start,end=match.span()
                if not any(start<b and end>a for a,b,_ in selected): selected.append((start,end,kind))
    selected.sort(); spans=[]; output=[]; cursor=0
    namespace=hashlib.sha256((segment.block_id+source).encode()).hexdigest()[:24]
    for index,(start,end,kind) in enumerate(selected):
        raw=source[start:end]; marker=f'⟦WB:{namespace}:{index}⟧'
        span=ProtectedSpan(f'{segment.block_id}:{index}',kind,raw,hashlib.sha256(raw.encode()).hexdigest(),start,end,marker)
        output.extend((source[cursor:start],marker)); spans.append(span); cursor=end
    output.append(source[cursor:])
    return ProtectedBlock(segment.block_id,''.join(output),tuple(spans))


def restore(block, candidate):
    expected=[span.marker for span in block.spans]
    found=MARKER.findall(candidate)
    if found!=expected:
        raise ValueError('PROTECTED_SPAN_MISSING_DUPLICATED_REORDERED_OR_NEW:'+block.block_id)
    result=candidate
    for span in block.spans:
        if hashlib.sha256(span.raw.encode()).hexdigest()!=span.sha256:
            raise ValueError('PROTECTED_SPAN_TAMPERED:'+span.id)
        result=result.replace(span.marker,span.raw,1)
    return result


def view_span_positions(segments,protected_blocks,targets):
    """UTF-8 offsets for the sole runtime context gateway's byte checks."""
    from app.runtime.context_gateway import ProtectedSpan as RuntimeSpan
    result=[]; view_prefix=0
    for segment,block,target in zip(segments,protected_blocks,targets):
        scan=0
        for span in block.spans:
            index=target.find(span.raw,scan)
            if index<0: raise ValueError('PROTECTED_SPAN_TARGET_MISSING')
            src_start=len((''.join(s.source for s in segments[:segment.order])+segment.source[:span.start]).encode())
            start=view_prefix+len(target[:index].encode()); end=start+len(span.raw.encode())
            result.append(RuntimeSpan(src_start,src_start+len(span.raw.encode()),start,end)); scan=index+len(span.raw)
        view_prefix+=len(target.encode())
    return tuple(result)
