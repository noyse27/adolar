"""Deterministic natural-language parser for Adolar filter rules.

The parser deliberately accepts a constrained, documented German vocabulary.
It never generates SQL; callers must pass its result through the regular
filter validator before executing it.
"""

from __future__ import annotations

import re


class SmartRuleParseError(ValueError):
    """A user-facing error raised for unsupported or ambiguous input."""

    def __init__(self, message: str):
        super().__init__(message)
        self.user_message = message


_FIELD_ALIASES = {
    "album": "album",
    "alben": "album",
    "albumtitel": "album",
    "titel": "title",
    "tracktitel": "title",
    "songtitel": "title",
    "interpret": "artist",
    "interpreten": "artist",
    "künstler": "artist",
    "kuenstler": "artist",
    "artist": "artist",
    "genre": "genre",
    "genres": "genre",
    "jahrzehnt": "decade",
    "jahrzehnte": "decade",
    "jahr": "year",
    "playcount": "playcount",
    "wiedergaben": "playcount",
    "abspielungen": "playcount",
    "hinzugefügt": "added",
    "hinzugefuegt": "added",
}
_FIELD_LABELS = {
    "album": "Album",
    "title": "Titel",
    "artist": "Interpret",
    "genre": "Genre",
    "decade": "Jahrzehnt",
    "year": "Jahr",
    "playcount": "Playcount",
    "added": "Hinzugefügt",
}
_FIELD_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _FIELD_ALIASES), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_JOIN_WORDS = {"und", "oder"}
_JOIN_FILLERS = {"als", "das", "der", "die", "den", "dem"}


def _unquote(value: str) -> str:
    value = value.strip().strip(" ,.;:")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value


def _field_matches(text: str) -> list[re.Match]:
    """Return field tokens that are not part of a quoted value."""
    matches = []
    quote: str | None = None
    cursor = 0
    for match in _FIELD_RE.finditer(text):
        for char in text[cursor:match.start()]:
            if char in {'"', "'"}:
                quote = None if quote == char else char if quote is None else quote
        if quote is None:
            matches.append(match)
        cursor = match.end()
    return matches


def _split_values(value_text: str) -> tuple[list[str], str]:
    """Split one field's values and return their logical group mode."""
    text = re.sub(r"^sowohl\s+", "", value_text.strip(), flags=re.IGNORECASE)
    separators = (
        ("beziehungsweise", "any"),
        ("bzw.", "any"),
        ("als auch", "all"),
        ("oder", "any"),
        ("und", "all"),
    )
    values: list[str] = []
    modes: set[str] = set()
    current: list[str] = []
    quote: str | None = None
    index = 0
    lowered = text.casefold()
    while index < len(text):
        char = text[index]
        if char in {'"', "'"}:
            quote = None if quote == char else char if quote is None else quote
            current.append(char)
            index += 1
            continue
        matched = None
        matched_mode = None
        if quote is None:
            if char == ",":
                matched = ","
                matched_mode = "comma"
            for separator, mode in separators:
                end = index + len(separator)
                if (lowered[index:end] == separator and
                        (index == 0 or text[index - 1].isspace()) and
                        (end == len(text) or text[end].isspace())):
                    matched = separator
                    matched_mode = mode
                    break
        if matched:
            value = _unquote("".join(current))
            if value:
                values.append(value)
            current = []
            modes.add(matched_mode)
            index += len(matched)
        else:
            current.append(char)
            index += 1
    value = _unquote("".join(current))
    if value:
        values.append(value)
    explicit_modes = modes - {"comma"}
    if len(explicit_modes) > 1:
        raise SmartRuleParseError(
            "Eine Werteliste darf nicht gleichzeitig mit „und“ und „oder“ verknüpft werden."
        )
    # Comma-separated lists are selections (ANY), unless an explicit
    # conjunction states that every value must match.
    mode = next(iter(explicit_modes), "any" if "comma" in modes else "any")
    return values, mode


def _pop_trailing_word(text: str) -> tuple[str, str]:
    """Return the text before its last whitespace-delimited word and that word."""
    end = len(text)
    while end > 0 and text[end - 1].isspace():
        end -= 1
    start = end
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return text[:start].rstrip(), text[start:end].casefold()


def _strip_trailing_connector(segment: str) -> tuple[str, str | None]:
    """Remove a trailing clause connector without regex backtracking."""
    prefix, last_word = _pop_trailing_word(segment)
    if last_word in _JOIN_FILLERS:
        before_connector, connector = _pop_trailing_word(prefix)
        if before_connector and connector in _JOIN_WORDS:
            return before_connector, connector
    if prefix and last_word in _JOIN_WORDS:
        return prefix, last_word
    return segment, None


def _parse_age(segment: str) -> tuple[str, int, str]:
    patterns = (
        ("within_last", r"^(?:ist\s+)?innerhalb\s+der\s+letzten\s+"),
        ("before", r"^(?:ist\s+)?vor\s+"),
    )
    for op, pattern in patterns:
        match = re.match(pattern, segment, re.IGNORECASE)
        if not match:
            continue
        value_text = segment[match.end():].strip()
        digit_end = 0
        while digit_end < len(value_text) and value_text[digit_end].isdecimal():
            digit_end += 1
        unit_text = value_text[digit_end:].strip().casefold()
        if digit_end == 0:
            break
        units = {
            "tag": "days", "tage": "days", "tagen": "days",
            "woche": "weeks", "wochen": "weeks",
            "monat": "months", "monate": "months", "monaten": "months",
            "jahr": "years", "jahre": "years", "jahren": "years",
        }
        if unit_text not in units:
            break
        return op, int(value_text[:digit_end]), units[unit_text]
    raise SmartRuleParseError(
        "Für ‚Hinzugefügt‘ werden zum Beispiel „vor 3 Wochen“ oder "
        "„innerhalb der letzten 2 Monate“ unterstützt."
    )


def _operator_and_values(
        field: str, segment: str,
) -> tuple[str, list[str], str | None, str]:
    segment = re.sub(r"^(?:die|der|das)\s+", "", segment.strip(), flags=re.IGNORECASE)
    if field == "added":
        op, value, unit = _parse_age(segment)
        return op, [str(value)], unit, "all"

    operator_patterns = (
        ("not_contains", r"^(?:enthält|enthalten|beinhaltet|beinhalten)\s+nicht\s+"),
        ("contains", r"^(?:enthält|enthalten|beinhaltet|beinhalten)\s+"),
        ("ne", r"^(?:ist\s+nicht|ist\s+ungleich|ungleich)\s+"),
        ("gt", r"^(?:ist\s+)?(?:größer|groesser|mehr|neuer)\s+als\s+"),
        ("lt", r"^(?:ist\s+)?(?:kleiner|weniger|älter|aelter)\s+als\s+"),
        ("eq", r"^(?:ist|gleich|entspricht)\s+"),
    )
    raw_op = None
    value_text = ""
    for candidate, pattern in operator_patterns:
        match = re.match(pattern, segment, re.IGNORECASE)
        if match:
            raw_op = candidate
            value_text = segment[match.end():].strip()
            break
    if raw_op is None and field in {"year", "decade", "playcount"}:
        # Natural numeric shorthand: "als Jahrzehnt 1980, 1990 oder 2000".
        first = segment.lstrip()[:1]
        if first.isdecimal() or first == "-":
            raw_op = "eq"
            value_text = segment.strip()
    if raw_op is None:
        raise SmartRuleParseError(
            f"Nach ‚{_FIELD_LABELS[field]}‘ fehlt ein unterstützter Vergleich "
            "wie „ist“, „enthält“, „größer als“ oder „kleiner als“."
        )

    values, value_mode = _split_values(value_text)
    if not values:
        raise SmartRuleParseError(f"Für ‚{_FIELD_LABELS[field]}‘ fehlt ein Wert.")

    if field in {"year", "decade", "playcount"}:
        if raw_op in {"contains", "not_contains"}:
            raise SmartRuleParseError(
                f"‚{_FIELD_LABELS[field]}‘ benötigt einen Zahlenvergleich wie „ist“."
            )
        op = raw_op
        if op == "eq" and len(values) > 1:
            # One track cannot equal several years, decades or playcounts at
            # once, so enumerations of exact numbers always mean ANY.
            value_mode = "any"
    elif field == "genre":
        # Genre tags frequently contain multiple combined values. Per product
        # semantics even "Genre ist Rap" therefore means a substring match.
        op = "not_contains" if raw_op in {"ne", "not_contains"} else "contains"
    else:
        op = {"eq": "equals", "ne": "not_equals"}.get(raw_op, raw_op)
        if op in {"gt", "lt"}:
            raise SmartRuleParseError(
                f"‚{_FIELD_LABELS[field]}‘ unterstützt „ist“ oder „enthält“, "
                "aber keinen Größenvergleich."
            )
    return op, values, None, value_mode


def _rule_for_value(field: str, op: str, value: str, unit: str | None) -> dict:
    rule: dict = {"field": field, "op": op}
    if field in {"year", "decade", "playcount", "added"}:
        number_match = re.fullmatch(r"(-?\d+)(?:er)?", value.strip(), re.IGNORECASE)
        if not number_match:
            raise SmartRuleParseError(
                f"‚{value}‘ ist kein gültiger Zahlenwert für ‚{_FIELD_LABELS[field]}‘."
            )
        rule["value"] = int(number_match.group(1))
    else:
        rule["value"] = value[:120]
    if unit:
        rule["unit"] = unit
    return rule


def _clause_node(field: str, segment: str) -> dict:
    op, values, unit, mode = _operator_and_values(field, segment)
    rules = [_rule_for_value(field, op, value, unit) for value in values]
    return rules[0] if len(rules) == 1 else {"mode": mode, "rules": rules}


def _combine_clauses(clauses: list[dict], connectors: list[str]) -> dict:
    # AND binds more tightly than OR. This also keeps one field's value list
    # inside its own nested ANY group.
    terms: list[list[dict]] = [[clauses[0]]]
    for connector, clause in zip(connectors, clauses[1:], strict=True):
        if connector == "oder":
            terms.append([clause])
        else:
            terms[-1].append(clause)
    nodes = [items[0] if len(items) == 1 else {"mode": "all", "rules": items}
             for items in terms]
    return nodes[0] if len(nodes) == 1 else {"mode": "any", "rules": nodes}


def _describe(node: dict) -> str:
    if "rules" in node:
        joiner = " UND " if node.get("mode") == "all" else " ODER "
        return "(" + joiner.join(_describe(child) for child in node["rules"]) + ")"
    labels = {
        "contains": "enthält", "not_contains": "enthält nicht",
        "equals": "ist exakt", "not_equals": "ist nicht exakt",
        "eq": "ist", "ne": "ist nicht", "gt": "ist größer als", "lt": "ist kleiner als",
        "before": "vor", "within_last": "innerhalb der letzten",
    }
    value = node["value"]
    if node.get("unit"):
        unit_labels = {"days": "Tagen", "weeks": "Wochen", "months": "Monaten", "years": "Jahren"}
        value = f"{value} {unit_labels[node['unit']]}"
    return f"{_FIELD_LABELS[node['field']]} {labels[node['op']]} {value}"


def parse_smart_rule(text: str) -> dict:
    """Parse constrained German natural language into an Adolar filter tree."""
    if not isinstance(text, str):
        raise SmartRuleParseError("Bitte gib die gewünschte Regel als Text ein.")
    text = re.sub(r"\s+", " ", text.replace("„", '"').replace("“", '"')).strip()
    if not text:
        raise SmartRuleParseError("Bitte gib die gewünschte Regel als Text ein.")
    if len(text) > 2000:
        raise SmartRuleParseError("Die smarte Eingabe darf höchstens 2000 Zeichen lang sein.")

    matches = _field_matches(text)
    if not matches:
        raise SmartRuleParseError(
            "Kein bekanntes Regelfeld gefunden. Unterstützt werden unter anderem "
            "Titel, Album, Interpret, Genre, Jahr und Jahrzehnt."
        )

    clauses: list[dict] = []
    connectors: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.end():end].strip()
        segment, connector = _strip_trailing_connector(segment)
        if not connector and index + 1 < len(matches):
            raise SmartRuleParseError(
                f"Vor ‚{matches[index + 1].group(1)}‘ fehlt „und“ oder „oder“."
            )
        field = _FIELD_ALIASES[match.group(1).casefold()]
        clauses.append(_clause_node(field, segment))
        if index + 1 < len(matches):
            connectors.append(connector or "und")

    tree = _combine_clauses(clauses, connectors)
    if "rules" not in tree:
        tree = {"mode": "all", "rules": [tree]}
    return {"filter": tree, "interpretation": _describe(tree)}
