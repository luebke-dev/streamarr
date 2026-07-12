"""Tiny boolean DSL for overlay conditions.

Grammar (everything JSON-serializable):

    expr   := {"all": [expr, …]}
            | {"any": [expr, …]}
            | {"not": expr}
            | leaf
    leaf   := {"field": "<dot.path>", "op": "<operator>", "value": <any>}
    op     := "eq" | "ne" | "gte" | "lte" | "gt" | "lt"
            | "in" | "not_in" | "contains" | "not_contains"
            | "truthy" | "falsy" | "matches"

Field paths are looked up in the context dict produced by
``build_render_context``. Unknown fields evaluate to ``None``. Missing
context keys never raise so a template can opt-in to new fields without
breaking old items.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

# Template ``matches`` patterns are admin-authored but still untrusted input.
_MAX_REGEX_PATTERN_LENGTH = 256  # reject implausibly long patterns
_MAX_REGEX_INPUT_LENGTH = 4096  # cap the string we search to bound cost
_REGEX_CACHE_MAXSIZE = 256  # LRU bound so distinct patterns can't grow memory

# Reject a quantifier applied to a group that itself contains a quantifier —
# the classic catastrophic-backtracking shape, e.g. "(a+)+" / "(a*)*".
_NESTED_QUANTIFIER_RE = re.compile(r"\([^()]*[+*{][^()]*\)[+*{]")

# Bounded LRU of compiled patterns keyed by the raw pattern string. A value of
# ``None`` memoises "rejected/invalid" so bad patterns aren't re-screened.
_RegexCache: "OrderedDict[str, re.Pattern | None]" = OrderedDict()


def _compiled_pattern(expected: str) -> re.Pattern | None:
    """Return a cached compiled pattern, or ``None`` if unsafe/invalid.

    Screens out over-long patterns and nested-quantifier ReDoS shapes before
    compiling, and keeps the cache bounded (LRU eviction) so a flood of
    distinct template patterns can't grow process memory without limit.
    """
    if expected in _RegexCache:
        _RegexCache.move_to_end(expected)
        return _RegexCache[expected]

    pattern: re.Pattern | None
    if len(expected) > _MAX_REGEX_PATTERN_LENGTH or _NESTED_QUANTIFIER_RE.search(
        expected
    ):
        pattern = None
    else:
        try:
            pattern = re.compile(expected, re.IGNORECASE)
        except re.error:
            pattern = None

    _RegexCache[expected] = pattern
    _RegexCache.move_to_end(expected)
    while len(_RegexCache) > _REGEX_CACHE_MAXSIZE:
        _RegexCache.popitem(last=False)
    return pattern


def evaluate_condition(
    expression: dict | None, context: dict[str, Any]
) -> bool:
    """Evaluate ``expression`` against ``context``. Empty → True."""
    if not expression:
        return True
    if "all" in expression:
        return all(
            evaluate_condition(child, context) for child in expression["all"]
        )
    if "any" in expression:
        children = expression["any"] or []
        if not children:
            return False
        return any(evaluate_condition(child, context) for child in children)
    if "not" in expression:
        return not evaluate_condition(expression["not"], context)
    return _evaluate_leaf(expression, context)


def _evaluate_leaf(leaf: dict, context: dict[str, Any]) -> bool:
    field = leaf.get("field")
    op = leaf.get("op", "eq")
    expected = leaf.get("value")
    actual = context.get(field) if field else None

    if op == "truthy":
        return bool(actual)
    if op == "falsy":
        return not bool(actual)
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "gte":
        return _coerce_numeric_compare(actual, expected, lambda a, b: a >= b)
    if op == "lte":
        return _coerce_numeric_compare(actual, expected, lambda a, b: a <= b)
    if op == "gt":
        return _coerce_numeric_compare(actual, expected, lambda a, b: a > b)
    if op == "lt":
        return _coerce_numeric_compare(actual, expected, lambda a, b: a < b)
    if op == "in":
        return _coerce_in(actual, expected, invert=False)
    if op == "not_in":
        return _coerce_in(actual, expected, invert=True)
    if op == "contains":
        return _coerce_contains(actual, expected, invert=False)
    if op == "not_contains":
        return _coerce_contains(actual, expected, invert=True)
    if op == "matches":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        pattern = _compiled_pattern(expected)
        if pattern is None:
            return False
        return bool(pattern.search(actual[:_MAX_REGEX_INPUT_LENGTH]))
    return False


def _coerce_numeric_compare(
    actual: Any, expected: Any, fn
) -> bool:
    try:
        a = float(actual)
        b = float(expected)
    except (TypeError, ValueError):
        return False
    return fn(a, b)


def _coerce_in(actual: Any, expected: Any, *, invert: bool) -> bool:
    """`actual in expected` with friendly list-vs-scalar handling."""
    if expected is None:
        return invert
    if isinstance(expected, (list, tuple, set)):
        haystack = {_lc(v) for v in expected}
    elif isinstance(expected, str):
        haystack = {_lc(expected)}
    else:
        haystack = {expected}
    needles: set
    if isinstance(actual, (list, tuple, set)):
        needles = {_lc(v) for v in actual}
        hit = bool(needles & haystack)
    else:
        hit = _lc(actual) in haystack
    return (not hit) if invert else hit


def _coerce_contains(
    actual: Any, expected: Any, *, invert: bool
) -> bool:
    """`expected in actual` — symmetric helper for "field includes value"."""
    if actual is None:
        return invert
    if isinstance(actual, (list, tuple, set)):
        hit = _lc(expected) in {_lc(v) for v in actual}
    elif isinstance(actual, str) and isinstance(expected, str):
        hit = expected.lower() in actual.lower()
    else:
        hit = actual == expected
    return (not hit) if invert else hit


def _lc(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value
