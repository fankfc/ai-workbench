"""Citation structure and bounded numerical recomputation, never claim support."""
import csv
from decimal import Decimal, InvalidOperation
import io
import json
import re
from .base import Observation, snapshot_bytes

PENDING = ("claim_support","bibliographic_authenticity","full_argument")


def validate(context, criterion, data):
    if criterion.evidence_type == "execution":
        if not context.data_inputs:
            return Observation("not_verified","DATA_UNAVAILABLE","csv_value_sum",pending_A_review=PENDING)
        try:
            total = Decimal(0)
            inputs = {}
            for name,snapshot in context.data_inputs.items():
                reader = csv.DictReader(io.StringIO(snapshot_bytes(context,snapshot).decode("utf-8")))
                if not reader.fieldnames or "value" not in reader.fieldnames:
                    return Observation("not_verified","DATA_SCHEMA_UNAVAILABLE","csv_value_sum",pending_A_review=PENDING)
                count = 0
                for row in reader:
                    value = Decimal(row["value"])
                    if not value.is_finite():
                        raise ValueError("NONFINITE_DATA")
                    total += value
                    count += 1
                if not count:
                    return Observation("not_verified","DATA_UNAVAILABLE","csv_value_sum",pending_A_review=PENDING)
                inputs[name] = {"revision_id":snapshot.revision_id,"sha256":snapshot.byte_sha256,"rows":count}
            text = data.decode("utf-8")
            try:
                supplied = Decimal(str(json.loads(text)["sum"]))
            except (ValueError,KeyError,TypeError):
                match = re.search(r"\bsum\s*[:=]\s*(-?\d+(?:\.\d+)?)",text)
                if match is None:
                    return Observation("not_verified","RECOMPUTED_RESULT_NOT_PRESENT","csv_value_sum",pending_A_review=PENDING)
                supplied = Decimal(match[1])
            if not supplied.is_finite():
                raise ValueError("NONFINITE_RESULT")
            details = {"inputs":inputs,"recomputed_sum":str(total),"candidate_sum":str(supplied)}
            return Observation("pass" if supplied == total else "fail","DATA_RECOMPUTED_MATCH" if supplied == total else "DATA_RECOMPUTED_MISMATCH","csv_value_sum",details,PENDING)
        except (UnicodeError,InvalidOperation,ValueError,KeyError):
            return Observation("fail","DATA_CORRUPT","csv_value_sum",pending_A_review=PENDING)
    if criterion.evidence_type != "artifact":
        return Observation("not_verified","CHECK_METHOD_UNAVAILABLE","paper_unavailable",pending_A_review=PENDING)
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        return Observation("fail","PAPER_TEXT_INVALID","citation_structure_only",pending_A_review=PENDING)
    sections = re.split(r"(?im)^\s*#{1,6}\s*(?:references|参考文献)\s*$",text,maxsplit=1)
    if len(sections) != 2:
        return Observation("fail","REFERENCE_SECTION_MISSING","citation_structure_only",pending_A_review=PENDING)
    cited = set(re.findall(r"\[(\d+)\]",sections[0]))
    defined = re.findall(r"(?m)^\s*\[(\d+)\]\s+\S",sections[1])
    if not cited or not cited.issubset(set(defined)) or len(defined) != len(set(defined)):
        return Observation("fail","CITATION_STRUCTURE_INVALID","citation_structure_only",{"cited":sorted(cited),"defined":defined},PENDING)
    return Observation("pass","CITATION_STRUCTURE_VALID","citation_structure_only",{"cited":sorted(cited),"defined":defined},PENDING)
