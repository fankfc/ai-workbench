import pytest
from app.translation.segments import segment_document,UnsupportedSyntax
from app.translation.protection import protect,restore

SOURCE='# 结果\n\n不能删除 `print("中文按钮")`；-0.03 与 95%。\n\n```python\nprint("保留原件")\n```\n\n| 项目 | 值 |\n| --- | --- |\n| 差值 | -0.03 |\n\nWindows C:\\data\\report.md DOI 10.1234/test；公式 $y=x^2$ [来源](https://example.org/a)。\n\n用户串 ⟦WB:collision:1⟧\n'

def test_markdown_ast_blocks_cover_and_roundtrip_exact_utf8_bytes():
    segments=segment_document(SOURCE)
    assert {'heading','paragraph','fence','table'}<=set(s.kind for s in segments)
    assert ''.join(s.source for s in segments)==SOURCE
    assert ''.join(restore(protect(s),protect(s).text) for s in segments).encode()==SOURCE.encode()
    assert all(s.source_sha256 and s.source_locator and s.document_version for s in segments)

@pytest.mark.parametrize('mutation',['missing','duplicate','new','reorder'])
def test_placeholder_attacks_cannot_restore(mutation):
    block=protect(segment_document('请保持 -0.03 和 95%。')[0]); text=block.text
    if mutation=='missing': text=text.replace(block.spans[0].marker,'')
    elif mutation=='duplicate': text+=block.spans[0].marker
    elif mutation=='new': text+='⟦WB:unknown:0⟧'
    else: text=text.replace(block.spans[0].marker,'TEMP').replace(block.spans[1].marker,block.spans[0].marker).replace('TEMP',block.spans[1].marker)
    with pytest.raises(ValueError,match='PROTECTED_SPAN'): restore(block,text)

def test_unsupported_footnote_and_long_structural_block_fail_explicitly():
    with pytest.raises(UnsupportedSyntax,match='FOOTNOTE'): segment_document('Fact[^1]\n\n[^1]: footnote')
    with pytest.raises(UnsupportedSyntax,match='TOO_LARGE'): segment_document('a'*50,max_chars=10)

def test_plain_text_split_preserves_sentence_and_parent_mapping():
    source='不要删除。 请保留。 只有成功。'
    blocks=segment_document(source,format='text',max_chars=10)
    assert ''.join(b.source for b in blocks)==source
    assert all(b.parent_block_id and len(b.source)<=10 for b in blocks)
