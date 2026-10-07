"""A finding says only what its Claims say (pilot-fixes ticket 21).

The research card's Editor writes each finding's statement; code holds it to the Claims the
finding cites. Every **number** (an amount, a count, a percentage, a year or a date's day)
and every **capitalised name** in the statement, and every phrase the statement puts in
quotation marks, must occur in the grounds: the quotes, subject names and objects of the
cited Claims, the research question (its own words are allowed) and the other names of any
company or term those already name (`ALIASES`: a company's display and legal names; a few
abbreviations of the domain, "InP" for "indium phosphide"). What doesn't is the finding's
`ungrounded` list (`ungrounded`).

What is matched, and how:
- Text goes through the typographic fold of the quote rule (`atlas.claims.predicates.fold`),
  then case is ignored. Quarters and halves are written one way on both sides ("second
  quarter" and "2Q" are "Q2"; "first half" and "1H" are "H1").
- A number is its value: separators dropped, a magnitude applied ("$600.1 million",
  "600,100,000" and "600.1m" are one value), with its unit when it has one (%, x, G, T, p:
  "200G" is not "200%"). A unit on one side only still matches. A currency must agree when
  both sides name one. A statement's number also matches the same figure before its magnitude
  (a table's "600.1" for "$600.1 million"). The grounds' number words ("three") count as
  numbers; the statement's number words are not checked.
- A name is each capitalised word of the statement (and each part of a hyphenated or slashed
  word: "InP-based", "CW/DFB"), a word mixing letters and digits ("GB200", "Q2"), not a
  function word (`_FUNCTION_WORDS`: "The", "However", ...). It must occur as a whole word; a
  plural or possessive "s" on either side is ignored. Neighbouring unfound words are reported
  as one name ("Deutsche Bank").
- A quoted phrase (in double quotation marks) must occur as written, whitespace, quotation
  marks of either kind and the punctuation at its two ends aside (a nested quotation, and the
  Editor's own claim labels such as "(c10, c15)", are handled before); an ellipsis splits it
  into pieces that must each occur.

What is not checked: the logic of a sentence (who did what to whom, a plan written as a fact,
two agreements written as one). The check holds names and figures; the rest stays the
reviewer's (`docs/decisions.md`, "A finding says only what its Claims say").
"""

import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from atlas.claims.predicates import fold
from atlas.roles.caller import RoleOutputQuarantined, TokenBudgetExhausted
from atlas.roles.contract import QuotedText
from atlas.roles.editor import (
    CardFindingDraft,
    EditorCardClaim,
    EditorRegroundRequest,
    EditorUngroundedFinding,
    RegroundedFindings,
)

# Terms written several ways in the domain: if the grounds name one, the others count too.
ALIASES: tuple[tuple[str, ...], ...] = (
    ("InP", "indium phosphide"),
    ("GaAs", "gallium arsenide"),
    ("GaN", "gallium nitride"),
    ("SiC", "silicon carbide"),
    ("SiPh", "silicon photonics"),
    ("Ge", "germanium"),
    ("pBN", "PBN", "pyrolytic boron nitride"),
    ("EML", "electro-absorption modulated laser", "externally modulated laser"),
    ("DML", "directly modulated laser"),
    ("DFB", "distributed feedback"),
    ("CW", "continuous wave", "continuous-wave"),
    ("UHP", "ultra-high power", "ultra high power", "ultra-high-power"),
    ("VCSEL", "vertical-cavity surface-emitting laser", "vertical cavity surface emitting laser"),
    ("CPO", "co-packaged optics", "co-packaged optical"),
    ("PIC", "photonic integrated circuit"),
    ("TIA", "transimpedance amplifier"),
    ("MOCVD", "metal-organic chemical vapor deposition", "metalorganic chemical vapor deposition"),
    ("MBE", "molecular beam epitaxy"),
    ("LTA", "long-term agreement", "long term agreement"),
    ("AI", "artificial intelligence"),
    ("U.S.", "US", "USA", "U.S.A.", "United States"),
    ("U.K.", "UK", "United Kingdom"),
    ("EU", "European Union"),
)

# Capitalised words that are never a name: articles, pronouns, conjunctions, prepositions and
# the adverbs a sentence starts with. Lower case.
_FUNCTION_WORDS = frozenset(
    """
    a an the this that these those it its they their them we our he she his her
    both each all any some no not none neither nor either every other another such same
    and but or so yet also however while whereas although though because since as if when
    where which who whom whose what why how than then there here thus hence therefore
    at by for from in into of on onto over under with without to after before during
    through across per via about against among between within upon
    separately additionally together meanwhile overall further furthermore moreover
    likewise similarly collectively notably specifically instead still already only
    most more many several few much less least
    is are was were be been being has have had do does did will would can could may might
    shall should must
    claim claims quote quotes finding findings
    """.split()
)

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "twenty": 20,
    "thirty": 30,
    "fifty": 50,
    "hundred": 100,
}
_MAGNITUDES: dict[str, Decimal] = {
    "thousand": Decimal(10) ** 3,
    "k": Decimal(10) ** 3,
    "million": Decimal(10) ** 6,
    "mn": Decimal(10) ** 6,
    "mm": Decimal(10) ** 6,
    "m": Decimal(10) ** 6,
    "billion": Decimal(10) ** 9,
    "bn": Decimal(10) ** 9,
    "b": Decimal(10) ** 9,
    "trillion": Decimal(10) ** 12,
    "tn": Decimal(10) ** 12,
}
_UNITS: dict[str, str] = {
    "%": "%",
    "percent": "%",
    "per cent": "%",
    "x": "x",
    "g": "g",
    "gig": "g",
    "gb": "g",
    "gbps": "g",
    "gbit": "g",
    "gigabit": "g",
    "t": "t",
    "tb": "t",
    "tbps": "t",
    "terabit": "t",
    "p": "p",
    "pence": "p",
}
_UNIT_WORDS = sorted({*_MAGNITUDES, *_UNITS}, key=len, reverse=True)
_NUMBER = re.compile(
    r"(?<![\w.])(?P<currency>[$£€¥])?\s?(?P<integer>\d{1,3}(?:,\d{3})+|\d+)(?P<fraction>\.\d+)?"
    r"(?:\s?-?\s?(?P<unit>%|(?:"
    + "|".join(re.escape(unit) for unit in _UNIT_WORDS if unit != "%")
    + r")(?![\w%])))?",
    re.IGNORECASE,
)
_QUARTERS = (
    (re.compile(r"\b(first|1st)\s+quarter\b", re.I), "Q1"),
    (re.compile(r"\b(second|2nd)\s+quarter\b", re.I), "Q2"),
    (re.compile(r"\b(third|3rd)\s+quarter\b", re.I), "Q3"),
    (re.compile(r"\b(fourth|4th)\s+quarter\b", re.I), "Q4"),
    (re.compile(r"\b([1-4])Q\b"), r"Q\1"),
    (re.compile(r"\b(first|1st)\s+half\b", re.I), "H1"),
    (re.compile(r"\b(second|2nd)\s+half\b", re.I), "H2"),
    (re.compile(r"\b([12])H\b"), r"H\1"),
)
_SUFFIX = re.compile(
    r",?\s+(?:Inc|Incorporated|Corp|Corporation|Co|Company|Ltd|Limited|plc|PLC|LLC|N\.V|S\.A"
    r"|AG|SE|GmbH|Holdings?(?:,?\s+(?:Inc|Corp|Ltd|plc|Co))?)\.?$"
)
_FISCAL_YEAR = re.compile(r"^(?:FY|CY)(\d{2}|\d{4})$", re.IGNORECASE)
_QUOTED = re.compile(r'"([^"]+)"')
_NESTED_QUOTE = re.compile(r'\("([^"()]+)"\)')
_PHRASE_EDGE = " .,;:!?-()[]"
_LABEL = re.compile(r"\bc\d{1,3}\b")
# "(c10, c15)", "c4 and c5", "claims c1, c2": labels in lower case, in a list
_LABELS = re.compile(r"\(?\bc\d{1,3}\b(?:\s*(?:,|;|&|and)\s*c\d{1,3}\b)*\)?")
_ELLIPSIS = re.compile(r"\.\.\.|…|\[[^\]]*\]")
_TOKEN = re.compile(r"[^\s,;:()\[\]{}\"!?]+")
_EDGE = "'."  # the statement is folded: its quotation marks are ASCII

# What the card says about this check (`ResearchCard.grounding_limit`; pilot-fixes ticket 25).
GROUNDING_LIMIT = (
    "A finding is checked for the names, figures and quoted phrases it uses, which must occur"
    " in the Claims it cites. Direction (who did what to whom), tense (a plan written as a"
    " fact) and the merging of two facts into one are not checked: a finding that passed can"
    " still misstate its Claims."
)


@dataclass(frozen=True)
class _Number:
    value: Decimal
    coefficient: Decimal  # before the magnitude
    scaled: bool  # a magnitude was applied
    unit: str | None
    currency: str | None


@dataclass(frozen=True)
class Grounds:
    """What a finding's statement may draw on, prepared once per finding."""

    text: str  # folded, normalised, lower case
    cased: str  # the same, as written (for short acronyms: "US" is not "us")
    numbers: tuple[_Number, ...]


def grounds(texts: Iterable[str], aliases: Iterable[Sequence[str]] = ()) -> Grounds:
    """The grounds made of `texts` (the cited Claims' quotes, subjects and objects, and the
    question), with every other name of an alias group (`aliases`, then `ALIASES`) one of
    whose names they contain."""
    joined = "\n".join(_normal(text) for text in texts)
    lowered = joined.lower()
    extra: list[str] = []
    for group in (*aliases, *ALIASES):
        written = [_normal(name) for name in group if name.strip()]
        # "Quantum Photonic Lasers Corp." is also "Quantum Photonic Lasers".
        names = list(dict.fromkeys([*written, *(_SUFFIX.sub("", name) for name in written)]))
        if any(_named(name, joined, lowered) for name in names):
            extra.extend(names)
    if extra:
        joined = joined + "\n" + "\n".join(extra)
    numbers = tuple(_numbers(joined)) + tuple(_word_numbers(joined))
    return Grounds(text=joined.lower(), cased=joined, numbers=numbers)


def ungrounded(statement: str, ground: Grounds) -> list[str]:
    """The numbers, names and quoted phrases of `statement` that `ground` doesn't contain, as
    the statement writes them (folded), in order and without repeats."""
    text = _without_labels(_nested_quotes(_normal(statement)), ground)
    found: list[str] = []
    flat_ground = _flat(ground.text)
    for phrase in _QUOTED.findall(text):
        pieces = [_flat(piece) for piece in _ELLIPSIS.split(phrase)]
        if any(piece and piece not in flat_ground for piece in pieces):
            found.append(f'"{phrase.strip()}"')
    for match in _NUMBER.finditer(text):
        number = _number(match)
        if number is not None and not any(_same(number, other) for other in ground.numbers):
            found.append(match.group(0).strip())
    for token in _TOKEN.findall(text):
        fiscal = _FISCAL_YEAR.match(token.strip(_EDGE))
        if fiscal and not any(_same(_year(fiscal.group(1)), n) for n in ground.numbers):
            found.append(token.strip(_EDGE))
    found.extend(_names(text, ground))
    return list(dict.fromkeys(found))


# --- helpers ------------------------------------------------------------------------------------


def _normal(text: str) -> str:
    folded = fold(text)
    for pattern, replacement in _QUARTERS:
        folded = pattern.sub(replacement, folded)
    return folded


def _flat(text: str) -> str:
    """`text` as a quoted phrase is compared: lower case, whitespace single, quotation marks of
    either kind dropped (a nested 'TSMC' for "TSMC"), and the punctuation at its ends (the
    Editor closes a quoted clause with a comma the source writes as a full stop) dropped."""
    plain = " ".join(text.lower().replace('"', "").replace("'", "").split())
    return plain.strip(_PHRASE_EDGE)


def _nested_quotes(text: str) -> str:
    """A quotation inside parentheses ("(\\"TSMC\\")") written with the other kind of mark, so
    it doesn't end the quoted phrase around it."""
    unescaped = text.replace('\\"', '"').replace("\\'", "'")  # a JSON escape left in the text
    return _NESTED_QUOTE.sub(r"('\1')", unescaped)


def _without_labels(text: str, ground: Grounds) -> str:
    """`text` without the Editor's own claim labels ("(c10, c15)"), which it writes into
    statements and which aren't figures; a label the grounds themselves contain stays."""

    def drop(match: re.Match[str]) -> str:
        labels = _LABEL.findall(match.group(0))
        if any(_occurs(label, ground.text) for label in labels):
            return match.group(0)
        return " "

    return _LABELS.sub(drop, text)


def _occurs(term: str, haystack: str) -> bool:
    """Whether lower-case `term` occurs in lower-case `haystack` as whole words (a plural or
    possessive "s" after it allowed)."""
    if not term:
        return True
    pattern = r"(?<![\w])" + re.escape(term) + r"(?:'?s|')?(?![\w])"
    return re.search(pattern, haystack) is not None


def _acronym(term: str) -> bool:
    """A short all-capitals word ("US", "AI", "CW"), matched with its case."""
    letters = term.rstrip("s") if len(term) > 2 else term
    return 2 <= len(letters) <= 3 and letters.isalpha() and letters.isupper()


def _named(term: str, cased: str, lowered: str) -> bool:
    if _acronym(term):
        return _occurs(term, cased)
    return _occurs(term.lower(), lowered)


def _number(match: re.Match[str]) -> _Number | None:
    try:
        coefficient = Decimal(match["integer"].replace(",", "") + (match["fraction"] or ""))
    except InvalidOperation:
        return None
    unit_word = (match["unit"] or "").lower()
    magnitude = _MAGNITUDES.get(unit_word)
    unit = _UNITS.get(unit_word)
    value = coefficient * magnitude if magnitude is not None else coefficient
    return _Number(
        value=value.normalize(),
        coefficient=coefficient.normalize(),
        scaled=magnitude is not None,
        unit=unit,
        currency=match["currency"],
    )


def _numbers(text: str) -> Iterable[_Number]:
    for match in _NUMBER.finditer(text):
        number = _number(match)
        if number is not None:
            yield number
    for token in _TOKEN.findall(text):
        fiscal = _FISCAL_YEAR.match(token.strip(_EDGE))
        if fiscal:
            yield _year(fiscal.group(1))


def _word_numbers(text: str) -> Iterable[_Number]:
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in _NUMBER_WORDS:
            value = Decimal(_NUMBER_WORDS[word])
            yield _Number(value=value, coefficient=value, scaled=False, unit=None, currency=None)


def _year(digits: str) -> _Number:
    value = Decimal(digits if len(digits) == 4 else "20" + digits)
    return _Number(value=value, coefficient=value, scaled=False, unit=None, currency=None)


def _same(number: _Number, other: _Number) -> bool:
    if number.unit and other.unit and number.unit != other.unit:
        return False
    if number.currency and other.currency and number.currency != other.currency:
        return False
    if number.value == other.value:
        return True
    # "$600.1 million" in the statement, "600.1" in a table of millions.
    return number.scaled and not other.scaled and number.coefficient == other.value


def _names(text: str, ground: Grounds) -> list[str]:
    """The statement's capitalised and alphanumeric words the grounds don't contain, runs of
    neighbouring ones joined."""
    missing: list[str] = []
    run: list[str] = []
    end = 0
    for token in _TOKEN.finditer(text):
        if run and text[end : token.start()].strip():
            # Punctuation between two words ("Zurich, Switzerland") ends a name.
            missing.append(_joined(run))
            run = []
        end = token.end()
        word = token.group(0)
        if word.strip(_EDGE).count(".") > 1:  # an abbreviation such as "U.S." or "U.S.-based"
            parts = [p.rstrip("'") for p in re.split(r"-(?=[a-z])", word)]
        else:
            parts = [part.strip(_EDGE) for part in re.split(r"[-/]", word)]
        unfound = [_bare(p) for p in parts if _is_name(p) and not _grounded(p, ground)]
        if unfound:
            run.extend(unfound)
            if word.endswith(".") and word.count(".") == 1:  # the sentence ends here
                missing.append(_joined(run))
                run = []
            continue
        if run and not any(_is_name(p) for p in parts) and word.lower() in _CONNECTORS:
            run.append(word)  # "Bank of Japan": keep the name open across a connector
            continue
        if run:
            missing.append(_joined(run))
            run = []
    if run:
        missing.append(_joined(run))
    return missing


def _joined(run: list[str]) -> str:
    while run and run[-1].lower() in _CONNECTORS:
        run = run[:-1]
    return " ".join(run)


_CONNECTORS = frozenset({"of", "&", "de", "du", "la", "von", "van"})


def _bare(part: str) -> str:
    """`part` without a possessive "'s" (as reported)."""
    return re.sub(r"(?:'s|')$", "", part)


def _is_name(part: str) -> bool:
    core = re.sub(r"(?:'s|')$", "", part)
    if not core or not core[0].isalpha():
        return False  # a number, checked as one
    if _FISCAL_YEAR.match(core):
        return False  # a year, checked as a number
    has_digit = any(ch.isdigit() for ch in core)
    if not (core[0].isupper() or has_digit):
        return False
    return core.lower() not in _FUNCTION_WORDS


def _grounded(part: str, ground: Grounds) -> bool:
    core = _bare(part)
    candidates = [core]
    if core.endswith("."):
        candidates.append(core.rstrip("."))
    if len(core) > 2 and core.endswith("s"):
        candidates.append(core[:-1])  # "EMLs" where the grounds say "EML"
    return any(_named(each, ground.cased, ground.text) for each in candidates)


def claim_grounds(
    question: str, cited: Iterable[Mapping[Any, Any]], aliases: Iterable[Sequence[str]] = ()
) -> Grounds:
    """The grounds of a finding citing `cited` accepted Claims (rows with their `quote`,
    `subject_name`, `object_name`, `object_text` and `source_title`; the source's title
    dates a call or a report): those texts and the research question."""
    texts = [question]
    for claim in cited:
        texts.extend(
            str(claim[key])
            for key in ("quote", "subject_name", "object_name", "object_text", "source_title")
            if claim.get(key)
        )
    return grounds(texts, aliases)


# --- the research card's findings, checked and asked again ------------------------------------

type Ask = Callable[[EditorRegroundRequest, list[QuotedText]], tuple[RegroundedFindings, uuid.UUID]]


@dataclass(frozen=True)
class CheckedFinding:
    draft: CardFindingDraft  # with the statement checked last
    cited: list[str]  # its Claims' references
    ungrounded: list[str]  # empty: grounded


@dataclass(frozen=True)
class CheckedFindings:
    findings: list[CheckedFinding]  # in the Editor's order
    asked_again: int  # findings sent back to the Editor
    repaired: int  # of those, grounded the second time
    role_call_id: uuid.UUID | None  # the call that asked again
    failure: str | None  # why that call gave no answer, if it didn't


def check_findings(
    drafts: Sequence[tuple[CardFindingDraft, list[str]]],
    claims: Mapping[str, Mapping[Any, Any]],
    question: str,
    aliases: Sequence[Sequence[str]],
    ask: Ask,
) -> CheckedFindings:
    """Check each finding (its draft and the references of the Claims it cites, each one a
    key of `claims`) against its cited Claims; send every ungrounded one back to the Editor in
    one call (`ask`), and check its new statement the same way. A finding the answer leaves
    out keeps its first statement and its ungrounded terms; a call that fails (its answer
    quarantined, or the run's token budget spent) leaves them all ungrounded."""
    grounds_of = [
        claim_grounds(question, [claims[ref] for ref in cited], aliases) for _, cited in drafts
    ]
    first = [
        CheckedFinding(draft, cited, ungrounded(draft.statement, ground))
        for (draft, cited), ground in zip(drafts, grounds_of, strict=True)
    ]
    again = {f"f{index + 1}": index for index, each in enumerate(first) if each.ungrounded}
    if not again:
        return CheckedFindings(first, 0, 0, None, None)
    refs = list(dict.fromkeys(ref for index in again.values() for ref in first[index].cited))
    request = EditorRegroundRequest(
        research_question=question,
        findings=[
            EditorUngroundedFinding(
                finding=key,
                statement=first[index].draft.statement,
                claim_refs=first[index].cited,
                ungrounded=first[index].ungrounded,
            )
            for key, index in again.items()
        ],
        claims=[
            EditorCardClaim(
                ref=ref,
                subject=claims[ref]["subject_name"],
                predicate=claims[ref]["predicate"],
                object=claims[ref]["object_name"] or claims[ref]["object_text"] or "",
                product=claims[ref]["product"],
                layer=claims[ref]["layer"],
                epistemic_type=claims[ref]["epistemic_type"],
                source_title=claims[ref]["source_title"],
                source_version_id=str(claims[ref]["source_version_id"]),
            )
            for ref in refs
        ],
    )
    retrieved = [
        QuotedText(
            id=ref,
            source=(
                f"{claims[ref]['source_version_id']}"
                f"#{claims[ref]['span_start']}-{claims[ref]['span_end']}"
            ),
            text=claims[ref]["quote"],
        )
        for ref in refs
    ]
    try:
        answer, role_call_id = ask(request, retrieved)
    except RoleOutputQuarantined as failure:
        return CheckedFindings(first, len(again), 0, failure.role_call_id, str(failure))
    except TokenBudgetExhausted as failure:
        return CheckedFindings(first, len(again), 0, None, str(failure))
    checked = list(first)
    for each in answer.findings:
        index = again.get(each.finding)
        if index is None or checked[index] is not first[index]:
            continue  # not a finding it was asked about, or answered twice: the first stands
        draft = first[index].draft.model_copy(update={"statement": each.statement})
        terms = ungrounded(each.statement, grounds_of[index])
        checked[index] = CheckedFinding(draft, first[index].cited, terms)
    repaired = sum(1 for index in again.values() if not checked[index].ungrounded)
    return CheckedFindings(checked, len(again), repaired, role_call_id, None)
