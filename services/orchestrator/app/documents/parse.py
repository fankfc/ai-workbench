"""Bounded, explicit format coverage. Unsupported features block completeness."""
import base64
import io
import re
import xml.etree.ElementTree as ET
import zipfile

from .model import DocumentModel, ParseIssue, block, digest


def parse_document(data, format, *, source_version_id, language):
    if not isinstance(data, bytes) or len(data) > 32_000_000:
        raise ValueError('DOCUMENT_BYTES_OR_SIZE_INVALID')
    blocks, issues, resources = [], [], {}
    issue = lambda code, loc, detail: issues.append(ParseIssue(code=code, source_locator=loc, detail=detail))
    try:
        if format in ('md', 'markdown'):
            _markdown(data.decode('utf-8'), blocks, issue, resources)
        elif format == 'docx':
            _docx(data, blocks, issue, resources)
        elif format == 'pdf':
            _pdf(data, blocks, issue, resources)
        else:
            issue('FORMAT_UNSUPPORTED', 'document', f'不支持完整解析 {format}；请提供 Markdown、DOCX 或可选文本 PDF。')
    except (UnicodeError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile, RuntimeError) as error:
        issue('DOCUMENT_CORRUPT', 'document', type(error).__name__)
    if not blocks and not issues:
        issue('DOCUMENT_EMPTY', 'document', '文件没有可核验正文。')
    return DocumentModel(source_version_id=source_version_id, source_bytes_sha256=digest(data), language=language,
        blocks=blocks, issues=issues, resources=resources)


def _markdown(text, blocks, issue, resources):
    from markdown_it import MarkdownIt
    parser = MarkdownIt('commonmark', {'html': True}).enable('table')
    tokens = parser.parse(text)
    stack, table_number, row, col = [], -1, -1, -1
    parent = None; list_item_blocks=[]
    for token_index,token in enumerate(tokens):
        if token.type in ('html_block', 'html_inline'):
            issue('UNSUPPORTED_HTML', f'line:{(token.map or [0])[0]+1}', '原始 HTML 无法作为完整安全文档交付。')
        if token.type=='blockquote_open':
            issue('MARKDOWN_QUOTATION_STRUCTURE_UNSUPPORTED',f'line:{(token.map or [0])[0]+1}','引用结构需要专门保留，不能降为普通正文。')
        if token.type=='ordered_list_open':
            issue('MARKDOWN_LIST_ORDERED_UNSUPPORTED',f'line:{(token.map or [0])[0]+1}','首版不支持保持编号列表；请提供无歧义正文或简单项目符号。')
        if token.type in ('bullet_list_open','ordered_list_open') and any(x in stack for x in ('bullet_list_open','ordered_list_open')):
            issue('MARKDOWN_LIST_NESTED_UNSUPPORTED',f'line:{(token.map or [0])[0]+1}','首版不支持嵌套列表，不能压平父子步骤。')
        if token.type=='list_item_open': list_item_blocks.append(0)
        if token.type=='list_item_close': list_item_blocks.pop()
        if token.type == 'table_open':
            table_number += 1; row = -1
        if token.type == 'tr_open':
            row += 1; col = -1
        if token.type in ('th_open', 'td_open'):
            col += 1
        if token.nesting == 1:
            stack.append(token.type)
        elif token.nesting == -1 and stack:
            stack.pop()
        if token.type == 'inline':
            kind = 'heading' if 'heading_open' in stack else 'table_cell' if any(x in stack for x in ('th_open', 'td_open')) else 'list_item' if 'list_item_open' in stack else 'paragraph'
            metadata = {}
            if kind=='list_item':
                list_item_blocks[-1]+=1
                if list_item_blocks[-1]>1:
                    issue('MARKDOWN_LIST_MULTIBLOCK_UNSUPPORTED',f'line:{(token.map or [0])[0]+1}','列表项的连续正文段不能拆成多个独立项目。')
                metadata.update(list_type='ordered' if 'ordered_list_open' in stack else 'unordered',
                    list_depth=sum(x in ('bullet_list_open','ordered_list_open') for x in stack))
            if kind == 'heading':
                previous = next(t for t in reversed(tokens[:token_index]) if t.type == 'heading_open')
                metadata['level'] = int(previous.tag[1:])
            if kind == 'table_cell':
                metadata.update(table=table_number, row=row, col=col, header='th_open' in stack)
            links, images = [], []
            for child in token.children or []:
                if child.type == 'link_open':
                    target = child.attrGet('href'); links.append(target)
                    if (target or '').startswith('#'):
                        issue('INTERNAL_ANCHOR_UNRESOLVED', f'line:{(token.map or [0])[0]+1}', '跨块锚点未核验。')
                    if not re.match(r'^(https?://|mailto:|#)', target or ''):
                        issue('RELATIVE_RESOURCE_UNRESOLVED', f'line:{(token.map or [0])[0]+1}', target or '')
                elif child.type == 'image':
                    images.append(child.attrGet('src'))
                    issue('IMAGE_RESOURCE_UNRESOLVED', f'line:{(token.map or [0])[0]+1}', '图片资源及图内文字需要独立核验。')
                elif child.type == 'html_inline':
                    issue('UNSUPPORTED_HTML', f'line:{(token.map or [0])[0]+1}', '不支持内联 HTML。')
            if links: metadata['links'] = links
            if images: metadata['images'] = images
            if re.search(r'\[\^|(?<!\\)\$|^:::', token.content):
                issue('MARKDOWN_EXTENSION_UNSUPPORTED', f'line:{(token.map or [0])[0]+1}', '脚注/数学/指令扩展需要专用解析能力。')
            value = block(kind, token.content, f'line:{(token.map or [0])[0]+1}', len(blocks), parent_id=parent, metadata=metadata)
            blocks.append(value)
            if kind == 'heading': parent = value.block_id
        elif token.type in ('fence', 'code_block'):
            blocks.append(block('code', token.content, f'line:{(token.map or [0])[0]+1}', len(blocks), parent_id=parent,
                translatable=False, metadata={'info': token.info}))
        elif token.type == 'hr':
            blocks.append(block('separator', '', f'line:{(token.map or [0])[0]+1}', len(blocks), translatable=False))


def _docx(data, blocks, issue, resources):
    w = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 64_000_000:
            raise ValueError('DOCX_RESOURCE_LIMIT')
        if '[Content_Types].xml' not in archive.namelist():
            raise ValueError('DOCX_CONTENT_TYPES_MISSING')
        for name in archive.namelist():
            if name.startswith('word/media/'):
                resources[name] = base64.b64encode(archive.read(name)).decode()
        parts = ['word/document.xml'] + [n for n in archive.namelist() if re.fullmatch(r'word/(footnotes|endnotes|header\d+|footer\d+)\.xml', n)]
        if 'word/comments.xml' in archive.namelist():
            issue('DOCX_COMMENTS_REQUIRE_REVIEW','word/comments.xml','批注内容需要独立来源与交付裁决。')
        for name in parts:
            root = ET.fromstring(archive.read(name))
            rel_name='word/_rels/'+name.split('/')[-1]+'.rels'
            relationships={}
            if rel_name in archive.namelist():
                for relation in ET.fromstring(archive.read(rel_name)):
                    relationships[relation.get('Id')]=relation
            def paragraph_text(p):
                values=[]
                for n in p.iter():
                    if n.tag==w+'t': values.append(n.text or '')
                    elif n.tag==w+'tab': values.append('\t')
                    elif n.tag==w+'br': values.append('\n')
                return ''.join(values)
            def paragraph_links(p):
                links=[]
                for n in p.iter(w+'hyperlink'):
                    rid=n.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                    relation=relationships.get(rid)
                    if relation is None:
                        issue('DOCX_HYPERLINK_UNRESOLVED',name,'超链接的关系记录缺失。')
                    else:
                        target=relation.get('Target',''); links.append(target)
                        if re.match(r'^(https?://|mailto:)',target) is None:
                            issue('DOCX_HYPERLINK_UNSAFE_OR_UNRESOLVED',name,target)
                return links
            if any(n.tag in (w+'ins', w+'del', w+'altChunk', w+'txbxContent', w+'object', w+'fldChar',w+'sdt',w+'sym') for n in root.iter()):
                issue('DOCX_COMPLEX_CONTENT_UNSUPPORTED', name, '修订、文本框、外部内容、对象或字段需要专门核验。')
            if any(n.tag.endswith('}oMath') for n in root.iter()):
                issue('DOCX_EQUATION_REQUIRES_REVIEW', name, '公式保留 XML；当前不承诺可完整转换。')
            if any(n.tag.endswith('}drawing') or n.tag.endswith('}pict') for n in root.iter()):
                issue('DOCX_IMAGE_REQUIRES_REVIEW', name, '嵌入图像保留，但图内文字与位置未核验。')
            body = root.find(w+'body') if name == 'word/document.xml' else root
            for index, element in enumerate(body):
                if element.tag == w+'tbl':
                    for ri, tr in enumerate(element.findall(w+'tr')):
                        for ci, tc in enumerate(tr.findall(w+'tc')):
                            if tc.find(w+'tbl') is not None:
                                issue('DOCX_NESTED_TABLE_UNSUPPORTED',name,'嵌套表格不能降为普通单元格。')
                            if any(n.tag in (w+'vMerge', w+'gridSpan') for n in tc.iter()):
                                issue('DOCX_MERGED_TABLE_UNSUPPORTED', name, '合并单元格需要结构核验。')
                            content = '\n'.join(paragraph_text(p) for p in tc.findall(w+'p'))
                            links=[uri for p in tc.findall(w+'p') for uri in paragraph_links(p)]
                            blocks.append(block('table_cell', content, f'{name}:table:{index}:row:{ri}:cell:{ci}', len(blocks),
                                metadata={'table': index, 'row': ri, 'col': ci, 'header': ri == 0,**({'links':links} if links else {})}))
                else:
                    paragraphs = [element] if element.tag == w+'p' else list(element.iter(w+'p'))
                    for pi, p in enumerate(paragraphs):
                        content = paragraph_text(p)
                        if not content.strip(): continue
                        kind = 'footnote' if 'footnotes' in name else 'endnote' if 'endnotes' in name else 'header' if 'header' in name else 'footer' if 'footer' in name else 'paragraph'
                        style = p.find(f'{w}pPr/{w}pStyle')
                        metadata = {}
                        links=paragraph_links(p)
                        if links: metadata['links']=links
                        if style is not None and re.fullmatch(r'Heading[1-6]', style.get(w+'val', '')):
                            kind = 'heading'; metadata['level'] = int(style.get(w+'val')[-1])
                        blocks.append(block(kind, content, f'{name}:element:{index}:paragraph:{pi}', len(blocks), metadata=metadata))


def _pdf(data, blocks, issue, resources):
    import pymupdf
    with pymupdf.open(stream=data, filetype='pdf') as pdf:
        if pdf.is_encrypted or len(pdf) > 1000:
            raise ValueError('PDF_ENCRYPTED_OR_TOO_LARGE')
        for pi, page in enumerate(pdf):
            values = [b for b in page.get_text('blocks') if b[6] == 0 and b[4].strip()]
            # MuPDF may merge distant columns into one block. Inspect line
            # boxes as well, so extraction order is never inferred from that.
            lines = [line['bbox'] for item in page.get_text('dict')['blocks']
                if item.get('type') == 0 for line in item['lines']]
            if any(a[0] < b[0] and a[2]+30 < b[0] and max(a[1], b[1]) < min(a[3], b[3])
                    for a in lines for b in lines):
                issue('PDF_READING_ORDER_AMBIGUOUS', f'page:{pi+1}', '存在跨栏正文，阅读顺序需要确认。')
            if not values:
                issue('PDF_OCR_REQUIRED', f'page:{pi+1}', '扫描/空白页不能确认正文；请提供可选文本原件。')
            for a in values:
                for b in values:
                    if a[0] < b[0] and a[2]+30 < b[0] and max(a[1], b[1]) < min(a[3], b[3]):
                        issue('PDF_READING_ORDER_AMBIGUOUS', f'page:{pi+1}', '存在跨栏正文，阅读顺序需要确认。')
                        break
            if page.get_images():
                issue('PDF_IMAGE_REQUIRES_REVIEW', f'page:{pi+1}', '图像中的文字和来源尚未核验。')
            links=page.get_links()
            for link in links:
                if not link.get('uri') or re.match(r'^(https?://|mailto:)',link['uri']) is None:
                    issue('PDF_REFERENCE_UNRESOLVED',f'page:{pi+1}','内部跳转或非网络引用需要核验。')
            for value in sorted(values, key=lambda b: (b[1], b[0])):
                content = value[4].rstrip('\n')
                if '\ufffd' in content or re.search(r'\w-\n\w', content):
                    issue('PDF_TEXT_AMBIGUOUS', f'page:{pi+1}', '缺字或断词无法确认。')
                related=[link['uri'] for link in links if link.get('uri') and pymupdf.Rect(value[:4]).intersects(link['from'])]
                blocks.append(block('paragraph', content, f'page:{pi+1}:bbox:{",".join(f"{n:.2f}" for n in value[:4])}', len(blocks),
                    metadata={'page': pi+1, 'bbox': list(value[:4]),**({'links':related} if related else {})}))
