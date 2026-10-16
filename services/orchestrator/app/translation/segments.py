"""Lossless, located Markdown AST blocks. Unsupported syntax fails explicitly."""
from dataclasses import dataclass, asdict
import hashlib
import re
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

PARSER_VERSION='markdown-it-py:4.0.0/commonmark+table'


@dataclass(frozen=True)
class Segment:
    block_id: str
    kind: str
    source: str
    source_locator: str
    source_sha256: str
    document_version: str
    source_start: int
    source_end: int
    parent_block_id: str | None = None
    order: int = 0

    def to_dict(self):
        return asdict(self)


class UnsupportedSyntax(ValueError):
    pass


def parser():
    return MarkdownIt('commonmark',{'html':True,'maxNesting':100}).enable('table')


def structure(text):
    tree=SyntaxTreeNode(parser().parse(text))
    return tuple((node.type,node.markup) for node in tree.walk() if node.type not in ('text','inline','root','code_inline'))


def segment_document(text, *, format='markdown', document_version=None, locator='text', max_chars=8192):
    if not isinstance(text,str) or not text.strip():
        raise ValueError('NONEMPTY_SOURCE_REQUIRED')
    version=document_version or hashlib.sha256(text.encode()).hexdigest()
    if format not in ('markdown','text'):
        raise UnsupportedSyntax('FORMAT_UNAVAILABLE:'+format)
    if format=='markdown' and re.search(r'\[\^[^\]]+\]',text):
        raise UnsupportedSyntax('FOOTNOTE_EXTENSION_UNAVAILABLE')
    if format=='markdown':
        tree=SyntaxTreeNode(parser().parse(text))
        lines=text.splitlines(keepends=True); offsets=[0]
        for line in lines: offsets.append(offsets[-1]+len(line))
        ranges=[]
        for node in tree.children:
            if node.map is None:
                raise UnsupportedSyntax('AST_SOURCE_LOCATION_UNAVAILABLE:'+node.type)
            start,end=node.map; ranges.append((offsets[start],offsets[end],node.type))
        # Reference definitions may be consumed by CommonMark without AST nodes.
        # Gaps remain exact source blocks and are protected by the protocol.
    else:
        ranges=[(match.start(),match.end(),'paragraph') for match in re.finditer(r'[^\r\n]+(?:\r?\n(?!\r?\n)[^\r\n]+)*',text)]
    result=[]; cursor=0
    def add(start,end,kind,parent=None):
        source=text[start:end]; digest=hashlib.sha256(source.encode()).hexdigest()
        block='b-'+hashlib.sha256(f'{version}:{start}:{end}'.encode()).hexdigest()[:20]
        result.append(Segment(block,kind,source,f'{locator}:chars={start}-{end}',digest,version,start,end,parent,len(result)))
    for start,end,kind in ranges:
        if start<cursor:
            raise UnsupportedSyntax('AST_OVERLAPPING_SOURCE')
        if start>cursor: add(cursor,start,'gap')
        if end-start>max_chars:
            if format=='markdown' or kind!='paragraph':
                raise UnsupportedSyntax('STRUCTURAL_BLOCK_TOO_LARGE:'+str(start))
            pieces=list(re.finditer(r'.*?[。！？.!?](?:\s|$)|.+$',text[start:end],re.S))
            if not pieces or any(len(piece.group())>max_chars for piece in pieces):
                raise UnsupportedSyntax('SENTENCE_TOO_LARGE:'+str(start))
            parent=f'parent:{start}:{end}'
            for piece in pieces: add(start+piece.start(),start+piece.end(),kind,parent)
        else: add(start,end,kind)
        cursor=end
    if cursor<len(text): add(cursor,len(text),'gap')
    if ''.join(block.source for block in result)!=text:
        raise UnsupportedSyntax('AST_COVERAGE_INCOMPLETE')
    return tuple(result)
