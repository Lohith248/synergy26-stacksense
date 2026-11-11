"""Safe JSON loading: one scenario object or an array of them (the public file is an array of six)."""
import json


class _Obj(dict):
    dups = ()


def _hook(pairs):
    d, dups = _Obj(), []
    for k, v in pairs:
        if k in d:
            dups.append(k)
        d[k] = v
    d.dups = tuple(dups)
    return d


def _reject_constant(name):
    raise ValueError(f"non-finite number {name} is not valid JSON")


def _float(s):
    v = float(s)
    if v in (float("inf"), float("-inf")):
        raise ValueError(f"number {s} is out of range")
    return v


def _dup_paths(node, prefix=""):
    out = []
    if isinstance(node, dict):
        for k in getattr(node, "dups", ()):
            out.append(f"{prefix}{k}")
        for k, v in node.items():
            out += _dup_paths(v, f"{prefix}{k}.")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _dup_paths(v, f"{prefix}[{i}].")
    return out


def loads(text):
    """-> (data, error_message_or_None). Rejects NaN/Infinity, overflowing numbers; BOM tolerated."""
    if text.startswith("﻿"):
        text = text[1:]
    if not text.strip():
        return None, "File is empty."
    try:
        return json.loads(text, object_pairs_hook=_hook, parse_constant=_reject_constant, parse_float=_float), None
    except (ValueError, RecursionError) as e:
        return None, f"Not valid JSON: {e}"


def parse_text(text):
    """Return one output document per scenario in the text."""
    from .run import evaluate, invalid_output
    data, err = loads(text)
    if err:
        return [invalid_output([{"field": "$", "message": err}], scenario_id=None)]
    items = data if isinstance(data, list) else [data]
    if isinstance(data, list) and not data:
        return [invalid_output([{"field": "$", "message": "Array contains no scenarios."}], scenario_id=None)]
    outs = []
    for i, item in enumerate(items):
        try:
            dups = _dup_paths(item)
        except RecursionError:
            outs.append(invalid_output([{"field": "$", "message": "JSON nesting is too deep."}], scenario_id=None))
            continue
        if dups:
            sid = item.get("scenario_id") if isinstance(item, dict) and isinstance(item.get("scenario_id"), str) else None
            outs.append(invalid_output([{"field": p.rstrip("."), "message": "Key appears more than once; ambiguous value."}
                                        for p in dups], scenario_id=sid))
        else:
            outs.append(evaluate(item))
    return outs
