import io
import zipfile

import pymupdf
import pytest


@pytest.mark.parametrize('language,text', [('en', '# Report\n\nJanuary 30. February 40. Increase 10.\n'), ('zh-CN', '# 报告\n\n一月 30。二月 40。增加 10。\n')])
def test_real_pdf_font_coverage_layout_and_page_images(language, text, tmp_path):
    from app.documents.parse import parse_document
    from app.documents.render import DocumentRenderer
    model = parse_document(text.encode(), 'markdown', source_version_id='s', language=language)
    rendered = DocumentRenderer().render(model, 'pdf', evidence_dir=tmp_path)
    assert rendered.qa['status'] == 'pass'
    assert rendered.data.startswith(b'%PDF')
    assert rendered.qa['font_sha256']
    assert rendered.qa['pages'] == len(rendered.page_images)
    assert all(path.is_file() for path in rendered.page_images)
    with pymupdf.open(stream=rendered.data, filetype='pdf') as pdf:
        assert '30' in ''.join(p.get_text() for p in pdf)
        assert pdf[0].get_fonts()


def test_missing_font_and_wide_table_do_not_silently_render(tmp_path):
    from app.documents.parse import parse_document
    from app.documents.render import DocumentRenderer
    model = parse_document('# 报告\n\n完整正文。'.encode(), 'markdown', source_version_id='s', language='zh-CN')
    with pytest.raises(ValueError, match='FONT_UNAVAILABLE'):
        DocumentRenderer(font_path=tmp_path / 'missing.ttf').render(model, 'pdf', evidence_dir=tmp_path)
    wide = parse_document(('|A|B|\n|---|---|\n|'+'X'*1000+'|30|\n').encode(), 'markdown', source_version_id='s', language='en')
    with pytest.raises(ValueError, match='TABLE_CELL_TOO_WIDE'):
        DocumentRenderer().render(wide, 'pdf', evidence_dir=tmp_path)


def test_docx_is_real_ooxml_and_visual_unavailability_is_explicit(tmp_path):
    from app.documents.parse import parse_document
    from app.documents.render import DocumentRenderer
    model = parse_document(b'# Report\n\nBody 30.', 'markdown', source_version_id='s', language='en')
    rendered = DocumentRenderer(docx_renderer=None).render(model, 'docx', evidence_dir=tmp_path)
    with zipfile.ZipFile(io.BytesIO(rendered.data)) as archive:
        assert b'Body 30.' in archive.read('word/document.xml')
    assert rendered.qa['status'] == 'blocked'
    assert rendered.qa['code'] == 'DOCX_VISUAL_RENDERER_UNAVAILABLE'


@pytest.mark.windows
def test_private_hidden_word_actually_renders_chinese_docx_pages(tmp_path):
    from app.documents.parse import parse_document
    from app.documents.render import DocumentRenderer
    model = parse_document('# 报告\n\n一月 30。二月 40。增加 10。'.encode(), 'markdown', source_version_id='s', language='zh-CN')
    rendered = DocumentRenderer().render(model, 'docx', evidence_dir=tmp_path)
    assert rendered.qa['status'] == 'pass'
    assert rendered.preview_pdf.startswith(b'%PDF')
    assert rendered.page_images


def test_markdown_roundtrip_keeps_ast_structure_and_unsafe_resources_block(tmp_path):
    from app.documents.parse import parse_document
    from app.documents.render import DocumentRenderer
    model = parse_document(b'# Report\n\n|Month|Amount|\n|---|---|\n|Jan|30|\n\n```python\nprint(30)\n```\n', 'markdown', source_version_id='s', language='en')
    rendered = DocumentRenderer().render(model, 'markdown', evidence_dir=tmp_path)
    assert rendered.qa['status'] == 'pass'
    parsed = parse_document(rendered.data, 'markdown', source_version_id='s', language='en')
    assert [b.content for b in parsed.blocks] == [b.content for b in model.blocks]
    malicious = parse_document(b'# Report\n\n[x](../../secret)', 'markdown', source_version_id='s', language='en')
    with pytest.raises(ValueError, match='DOCUMENT_PARSE_INCOMPLETE'):
        DocumentRenderer().render(malicious, 'markdown', evidence_dir=tmp_path)


def test_pdf_preserves_source_citation_link_as_actual_annotation(tmp_path):
    from app.documents.parse import parse_document
    from app.documents.render import DocumentRenderer
    model=parse_document(b'# Report\n\n[Source](https://example.com/evidence)', 'markdown',source_version_id='s',language='en')
    result=DocumentRenderer().render(model,'pdf',evidence_dir=tmp_path)
    with pymupdf.open(stream=result.data,filetype='pdf') as pdf:
        assert any(link.get('uri')=='https://example.com/evidence' for link in pdf[0].get_links())


def test_pdf_cannot_reuse_one_actual_paragraph_for_two_required_blocks(tmp_path):
    from app.documents.parse import parse_document
    from app.documents.render import DocumentRenderer,verify_pdf
    full=parse_document(b'# Report\n\nRequired paragraph 30.\n\nRequired paragraph 30.',
        'markdown',source_version_id='full',language='en')
    omitted=parse_document(b'# Report\n\nRequired paragraph 30.',
        'markdown',source_version_id='omitted',language='en')
    actual_pdf=DocumentRenderer().render(omitted,'pdf',evidence_dir=tmp_path/'one').data
    with pytest.raises(ValueError,match='PDF_CONTENT_MISSING'):
        verify_pdf(actual_pdf,full,tmp_path)


def test_pdf_block_order_and_multiplicity_are_consumed_without_overlap(tmp_path):
    from app.documents.parse import parse_document
    from app.documents.render import DocumentRenderer,verify_pdf
    full=parse_document(b'# Report\n\nFirst required paragraph 30.\n\nSecond required paragraph 40.',
        'markdown',source_version_id='full',language='en')
    reversed_model=parse_document(b'# Report\n\nSecond required paragraph 40.\n\nFirst required paragraph 30.',
        'markdown',source_version_id='reverse',language='en')
    actual_pdf=DocumentRenderer().render(reversed_model,'pdf',evidence_dir=tmp_path/'reverse').data
    with pytest.raises(ValueError,match='PDF_CONTENT_MISSING'):
        verify_pdf(actual_pdf,full,tmp_path)
