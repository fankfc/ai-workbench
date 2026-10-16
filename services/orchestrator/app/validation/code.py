"""Syntax is mechanical; execution requires an actual authorized runner."""
import ast
from .base import Observation, run_command


def validate(context, criterion, data):
    if criterion.evidence_type == "execution":
        return run_command(context,criterion,"native_code_execution")
    if criterion.evidence_type != "artifact":
        return Observation("not_verified","CHECK_METHOD_UNAVAILABLE","code_unavailable")
    try:
        ast.parse(data.decode("utf-8"))
    except (UnicodeError,SyntaxError,ValueError):
        return Observation("fail","CODE_SYNTAX_INVALID","python_ast_parse")
    return Observation("pass","PYTHON_SYNTAX_VALID","python_ast_parse",pending_A_review=("overall_design",))
