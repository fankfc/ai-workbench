"""Actual container/text structure and token consistency against source bytes."""
from collections import Counter
from decimal import Decimal
import io
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
import struct
import zlib
from .base import Observation, run_command, snapshot_bytes


def text_of(data):
    if data.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if "[Content_Types].xml" not in archive.namelist():
                raise ValueError("DOCX_CONTENT_TYPES_MISSING")
            if archive.getinfo("word/document.xml").file_size>16_000_000:
                raise ValueError("DOCX_XML_TOO_LARGE")
            xml = archive.read("word/document.xml")
            tree = ET.fromstring(xml)
            return "\n".join(node.text or "" for node in tree.iter() if node.tag.endswith("}t"))
    if data.startswith(b"%PDF"):
        raise ValueError("PDF_RENDERER_REQUIRED")
    return data.decode("utf-8")


def _numbers(text):
    return Counter(Decimal(value) for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])",text))


def _valid_png(data):
    """Verify a bounded noninterlaced 8-bit RGB/RGBA rendering, including CRC."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    position, compressed, header, ended = 8,bytearray(),None,False
    try:
        while position<len(data):
            length=struct.unpack(">I",data[position:position+4])[0]
            kind=data[position+4:position+8]
            chunk=data[position+8:position+8+length]
            crc=struct.unpack(">I",data[position+8+length:position+12+length])[0]
            if len(chunk)!=length or zlib.crc32(kind+chunk)&0xffffffff!=crc:
                return False
            if kind==b"IHDR":
                if header is not None or position!=8 or length!=13:
                    return False
                header=struct.unpack(">IIBBBBB",chunk)
            elif kind==b"IDAT":
                compressed.extend(chunk)
            elif kind==b"IEND":
                ended=length==0 and position+12==len(data)
                break
            position+=12+length
        if not header or not ended:
            return False
        width,height,depth,color,compression,filter_method,interlace=header
        if not width or not height or depth!=8 or color not in (2,6) or compression or filter_method or interlace:
            return False
        stride=width*(3 if color==2 else 4)+1
        expected=stride*height
        if expected>16_000_000:
            return False
        inflater=zlib.decompressobj()
        pixels=inflater.decompress(bytes(compressed),expected+1)
        return inflater.eof and len(pixels)==expected and all(pixels[offset]<=4 for offset in range(0,expected,stride))
    except (struct.error,zlib.error,ValueError):
        return False


def validate(context, criterion, data):
    if criterion.evidence_type == "render":
        output=context.rendered_paths.get(criterion.id)
        output=Path(output) if output is not None else None
        # Refuse stale outputs before a command can overwrite them. Renderer
        # evidence must come from a fresh service-selected scoped destination.
        if output is not None:
            root=Path(context.workspace).resolve()
            if not output.resolve().is_relative_to(root) or output.is_symlink() or any(parent.is_symlink() or (hasattr(parent,"is_junction") and parent.is_junction()) for parent in output.parents if parent.is_relative_to(root)):
                return Observation("blocked","RENDERED_ARTIFACT_SCOPE_INVALID","native_document_renderer")
            if output.exists():
                return Observation("blocked","RENDER_OUTPUT_ALREADY_EXISTS","native_document_renderer")
        elif context.runner is not None and context.commands.get(criterion.id):
            return Observation("blocked","RENDER_OUTPUT_PATH_REQUIRED","native_document_renderer")
        observed=run_command(context,criterion,"native_document_renderer")
        if observed.status!="pass":
            return observed
        if output is None or not output.is_file():
            return Observation("fail","RENDERED_ARTIFACT_MISSING","native_document_renderer",observed.details)
        import hashlib
        if output.is_symlink() or not output.resolve().is_relative_to(Path(context.workspace).resolve()) or output.stat().st_size>16_000_000:
            return Observation("fail","RENDERED_ARTIFACT_SCOPE_INVALID","native_document_renderer")
        rendered=output.read_bytes()
        if not _valid_png(rendered):
            return Observation("not_verified","RENDER_OUTPUT_OPENABILITY_UNVERIFIED","native_document_renderer",observed.details)
        return Observation("pass","RENDERED_PNG_VERIFIED","native_document_renderer",{**observed.details,"rendered_ref":output.relative_to(Path(context.workspace)).as_posix(),"rendered_sha256":hashlib.sha256(rendered).hexdigest()},("visual_quality",))
    if criterion.evidence_type != "artifact":
        return Observation("not_verified","CHECK_METHOD_UNAVAILABLE","document_unavailable")
    try:
        text = text_of(data)
        if not text.strip():
            return Observation("fail","DOCUMENT_EMPTY","document_structure_and_source_tokens")
        if context.source is None:
            return Observation("not_verified","SOURCE_UNAVAILABLE","document_structure_and_source_tokens",pending_A_review=("document_completeness",))
        source = text_of(snapshot_bytes(context,context.source))
        if _numbers(text) != _numbers(source):
            return Observation("fail","SOURCE_NUMBERS_MISMATCH","document_structure_and_source_tokens")
        names = set(context.protected_names)
        names.update(value.strip() for value in re.findall(r"(?im)^\s*(?:name|姓名|名称)\s*[:：]\s*([^\r\n]+)",source))
        if any(name not in source or name not in text for name in names):
            return Observation("fail","SOURCE_NAMES_MISMATCH","document_structure_and_source_tokens")
        headings = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$",source)
        if any(heading not in text for heading in headings):
            return Observation("fail","DOCUMENT_SECTION_MISSING","document_structure_and_source_tokens")
        return Observation("pass","DOCUMENT_STRUCTURE_AND_TOKENS_MATCH","document_structure_and_source_tokens",{"source_revision_id":context.source.revision_id,"source_sha256":context.source.byte_sha256,"protected_names":sorted(names)},("document_completeness","overall_design"))
    except ValueError as error:
        if str(error)=="PDF_RENDERER_REQUIRED":
            return Observation("blocked","PDF_RENDERER_REQUIRED","document_structure_and_source_tokens")
        return Observation("fail","DOCUMENT_CORRUPT","document_structure_and_source_tokens")
    except (UnicodeError,KeyError,zipfile.BadZipFile,ET.ParseError):
        return Observation("fail","DOCUMENT_CORRUPT","document_structure_and_source_tokens")
