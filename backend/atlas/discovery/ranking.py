"""Lead ranking: how relevant a search result is to the query that found it, and its purpose.

A pure function of the result (URL, title, snippet), the query, the query's purpose, the
universe's company names and sites, and the ranking config
(`configs/discovery/lead-ranking.yaml`). Nothing is fetched. The score (0 to about 100) adds
up (`docs/decisions.md`, "Lead ranking"):

- **Query terms** (up to 60): the share of the query's topic terms the result names: a term
  in the title counts 1, in the snippet only 0.6. The topic terms are the query's words
  (lowercased, stopwords dropped, a plural `s` ignored) less the universe company names it
  contains (matched as below) and years (`2026`: a snippet's date matches them). So a query
  "Lumentum 200G EML chip allocation" asks about 200G EML chip allocation, and a page that
  only names Lumentum matches none of it.
- **Purpose terms** (up to 10): the share of the purpose's terms that aren't query terms
  the result names (title or snippet).
- **Companies** (4 each, up to 8): the universe companies the result names, by display or
  legal name, matched case-sensitively as written (a proper noun: "Coherent" the company,
  not "coherent" the adjective of a dictionary entry).
- **Product and layer terms** (3 each, up to 15): the config's `terms` (products, materials
  and layers) and `method_terms` (the bottleneck method's vocabulary) the result names.

**An EDGAR filing hit** (version 3; "Specific filing phrases") is scored the same way, against
the query whose filing phrase found it and that query's purpose. EDGAR returns no text, so
its title is `<filer> <form> filed <date>` and its snippet Atlas's own sentence naming the
phrases EDGAR matched: what is scored is how much of the query's topic the filing is known
to contain. A hit whose search matched one phrase that is itself a vocabulary term
(`matched`: "VCSEL", "CW laser", "export controls") is multiplied by `bare_term_factor`: every
industry that uses the thing writes the bare term, so the filer may be a lidar or a
medical-laser maker. A phrase that says more than a term ("InP substrates") and a search of
several phrases (all had to match) are not.

Then the penalties multiply: a demoted host (encyclopedias, quote pages, profile and social
sites; an entry may name a path, `bloomberg.com/profile`) by `demoted_host_factor`, a
universe company's own site (`company_sites`, from the universe's websites, plus the
config's `company_domains`) by `company_site_factor`, a generic title (a part of the title,
split at `|`, ` - ` and the like, that is one of the config's `generic_titles`: "About us",
"Investor Relations", "Homepage") by `generic_title_factor`, a result that doesn't read as
English by `non_english_factor`. A denied host (dictionaries, translation sites) is never
kept, whatever it scores; nor is a result naming no query topic term (a company name alone
never keeps a lead), nor one scoring below `min_score`. Each score carries its reasons, in
words, so an investigation can show why each lead was kept.

**English.** A result reads as non-English when it looks foreign (more than 3% of its
letters are outside ASCII: å, ö, é, a non-Latin script; or it has at least two common
function words of another language: Swedish, German, Dutch, French, Spanish, Italian "och",
"und", "les", "para", ...) and has no more English function words than foreign ones. So an
English headline naming "Société Générale" stays English, and a headline with no function
word at all (common) is English unless its letters say otherwise.
"""

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

QUERY_WEIGHT = 60.0
TITLE_HIT = 1.0
SNIPPET_HIT = 0.6
PURPOSE_WEIGHT = 10.0
COMPANY_POINTS = 4.0
COMPANY_CAP = 8.0
TERM_POINTS = 3.0
TERM_CAP = 15.0
NON_ASCII_LIMIT = 0.03
FOREIGN_MIN_WORDS = 2

# Common English function words: dropped from query terms, and counted to tell English.
_FUNCTION_WORDS = frozenset(
    "a an and or of to in on for with by at from as is are was were be been it its this that"
    " these those will would has have had how what who which why when where can could not no"
    " new into over after about more than per via vs their our we they he she you your"
    " but if so do does did".split()
)
# Common function words of other languages the engines answer in, none of them English.
_FOREIGN_WORDS = frozenset(
    "och att det för på är med som av till inte har vid eller ett sig från också"  # sv
    " und der das ist nicht mit auf für von zu sich dem den des eine einen"  # de
    " het een niet voor zijn wordt ook"  # nl
    " les du et est une pour dans sur avec aux qui ce cette sont"  # fr
    " el los las del y que por para una"  # es
    " il della che sono gli".split()  # it
)
_WORD = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
_ANY_WORD = re.compile(r"[^\W\d_]+")
_YEAR = re.compile(r"(?:19|20)\d\d")
# Where a title's parts divide: "About Us | Coherent", "Lumentum - Investor Relations" (a
# hyphen, en or em dash, colon, middle dot or bullet between spaces; a bar or dot anywhere).
_TITLE_PARTS = re.compile(r"\s+[-\u2013\u2014:\u00b7\u2022|]+\s+|\s*[|\u00b7\u2022]\s*")


class RankingConfigError(ValueError):
    """The lead ranking config is missing or invalid; the message says where."""


class RankingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    min_score: float = Field(ge=0, le=100)
    demoted_host_factor: float = Field(ge=0, le=1)
    company_site_factor: float = Field(ge=0, le=1)
    generic_title_factor: float = Field(ge=0, le=1)
    non_english_factor: float = Field(ge=0, le=1)
    denied_hosts: tuple[str, ...] = ()
    demoted_hosts: tuple[str, ...] = ()
    company_domains: tuple[str, ...] = ()
    generic_titles: tuple[str, ...] = ()
    # A filing hit whose EDGAR search matched one phrase that is itself a vocabulary term.
    bare_term_factor: float = Field(default=1.0, ge=0, le=1)
    terms: tuple[str, ...] = ()  # the product and layer terms
    method_terms: tuple[str, ...] = ()  # the bottleneck method's vocabulary

    @property
    def vocabulary(self) -> tuple[str, ...]:
        """Every term a result is scored for naming: the product and layer terms, then the
        bottleneck method's."""
        return tuple(dict.fromkeys((*self.terms, *self.method_terms)))


def load_ranking_config(path: Path) -> RankingConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RankingConfigError(f"lead ranking config {path}: {error}") from None
    try:
        return RankingConfig.model_validate(raw)
    except ValidationError as error:
        raise RankingConfigError(f"lead ranking config {path}: {error}") from None


class LeadScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float  # rounded to one decimal
    kept: bool  # not a denied host and at least `min_score`
    denied: bool  # a denied host
    reasons: list[str]  # why it scored what it did, in words


def _stem(word: str) -> str:
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def words(text: str) -> list[str]:
    """Lowercased words (a hyphenated word split in two), each with a plural `s` dropped."""
    return [_stem(part) for token in _WORD.findall(text.lower()) for part in token.split("-")]


def _terms(text: str) -> list[str]:
    """The distinct content words of `text`, in order."""
    seen: dict[str, None] = {}
    for word in words(text):
        if word not in _FUNCTION_WORDS:
            seen.setdefault(word, None)
    return list(seen)


def term_key(term: str) -> str:
    """A term as ranking compares it: its words, lowercased, a plural `s` dropped."""
    return " ".join(words(term))


def _phrase_in(phrase: str, text: str) -> bool:
    return f" {term_key(phrase)} " in text


def _host_in(host: str, hosts: Iterable[str], path: str = "/") -> str | None:
    """The first entry the host is or is a subdomain of; an entry with a path
    (`bloomberg.com/profile`) also needs the URL's path to start with it."""
    for entry in hosts:
        entry = entry.lower().removeprefix("www.")
        domain, slash, prefix = entry.partition("/")
        if slash and not (path == f"/{prefix}" or path.startswith(f"/{prefix.rstrip('/')}/")):
            continue
        if host == domain or host.endswith(f".{domain}"):
            return entry
    return None


def site_host(url: str) -> str:
    """A URL's host, lowercased, without `www.` (a company website's, as `company_sites`)."""
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _names(name: str, text: str) -> bool:
    """Whether `text` names `name` as written (case-sensitive, whole words)."""
    return bool(name) and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def _generic_title(title: str, generic: Iterable[str]) -> str | None:
    """The part of the title that is a generic page name ("About Us | Coherent": about us)."""
    wanted = {" ".join(_ANY_WORD.findall(each.lower())) for each in generic}
    for part in _TITLE_PARTS.split(title):
        name = " ".join(_ANY_WORD.findall(part.lower()))
        if name and name in wanted:
            return name
    return None


def _bare_term(matched: Sequence[str], config: RankingConfig) -> str | None:
    """The vocabulary term a filing hit's one matched phrase is ("VCSEL", "CW laser"), as the
    config writes it; None for a web result, a phrase that is more than a term ("InP
    substrates") and a search of several phrases (all of them had to match)."""
    if len(matched) != 1:
        return None
    key = term_key(matched[0])
    return next((term for term in config.vocabulary if term_key(term) == key), None)


def reads_as_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    non_ascii = sum(1 for c in letters if not c.isascii()) / len(letters) if letters else 0.0
    words = _ANY_WORD.findall(text.lower())
    foreign = sum(1 for w in words if w in _FOREIGN_WORDS)
    english = sum(1 for w in words if w in _FUNCTION_WORDS)
    looks_foreign = non_ascii > NON_ASCII_LIMIT or foreign >= FOREIGN_MIN_WORDS
    return not (looks_foreign and foreign >= english)


def score_lead(
    *,
    url: str,
    title: str,
    snippet: str,
    query: str,
    purpose: str | None,
    companies: Sequence[str],
    config: RankingConfig,
    company_sites: Sequence[str] = (),
    matched: Sequence[str] = (),
) -> LeadScore:
    """The relevance of one search result to its query and purpose (see the module).
    `matched`: for an EDGAR filing hit, the exact phrases the search matched in the filing."""
    host = site_host(url)
    path = urlsplit(url).path or "/"
    title_words = set(words(title))
    snippet_words = set(words(snippet))
    both = f" {' '.join(words(title))} | {' '.join(words(snippet))} "
    reasons: list[str] = []

    # The topic of the query and the purpose: their terms less the company names they
    # contain, and years.
    asked = f"{query}\n{purpose or ''}"
    named_words = {word for name in companies if _names(name, asked) for word in words(name)}

    def topic(text: str) -> list[str]:
        return [t for t in _terms(text) if t not in named_words and _YEAR.fullmatch(t) is None]

    query_terms = topic(query)
    in_title = [t for t in query_terms if t in title_words]
    in_snippet = [t for t in query_terms if t not in title_words and t in snippet_words]
    score = 0.0
    if query_terms:
        hits = TITLE_HIT * len(in_title) + SNIPPET_HIT * len(in_snippet)
        score += QUERY_WEIGHT * hits / len(query_terms)
    if in_title:
        reasons.append(f"query terms in the title: {', '.join(in_title)}")
    if in_snippet:
        reasons.append(f"query terms in the snippet: {', '.join(in_snippet)}")
    if not in_title and not in_snippet:
        reasons.append("no query term")

    purpose_terms = [t for t in topic(purpose or "") if t not in query_terms]
    purpose_hits = [t for t in purpose_terms if t in title_words or t in snippet_words]
    if purpose_hits:
        score += PURPOSE_WEIGHT * len(purpose_hits) / len(purpose_terms)
        reasons.append(f"purpose terms: {', '.join(purpose_hits)}")

    raw = f"{title}\n{snippet}"
    named = sorted({name for name in companies if _names(name, raw)})
    if named:
        score += min(COMPANY_POINTS * len(named), COMPANY_CAP)
        reasons.append(f"names {', '.join(named)}")

    terms = [t for t in config.vocabulary if _phrase_in(t, both)]
    if terms:
        score += min(TERM_POINTS * len(terms), TERM_CAP)
        reasons.append(f"product and layer terms: {', '.join(terms)}")

    bare = _bare_term(matched, config)
    if bare is not None:
        score *= config.bare_term_factor
        reasons.append(f'matched only the vocabulary term "{bare}" (x{config.bare_term_factor:g})')
    demoted = _host_in(host, config.demoted_hosts, path)
    if demoted is not None:
        score *= config.demoted_host_factor
        reasons.append(f"demoted host {demoted} (x{config.demoted_host_factor:g})")
    own = _host_in(host, (*company_sites, *config.company_domains))
    if own is not None:
        score *= config.company_site_factor
        reasons.append(f"a company's own site {own} (x{config.company_site_factor:g})")
    generic = _generic_title(title, config.generic_titles)
    if generic is not None:
        score *= config.generic_title_factor
        reasons.append(f'generic title "{generic}" (x{config.generic_title_factor:g})')
    if not reads_as_english(raw):
        score *= config.non_english_factor
        reasons.append(f"not English (x{config.non_english_factor:g})")

    score = round(score, 1)
    denied = _host_in(host, config.denied_hosts, path)
    on_topic = bool(in_title or in_snippet)
    if denied is not None:
        reasons.append(f"denied host {denied}")
    elif not on_topic:
        reasons.append("not kept without a query term")
    elif score < config.min_score:
        reasons.append(f"below the minimum score {config.min_score:g}")
    return LeadScore(
        score=score,
        kept=denied is None and on_topic and score >= config.min_score,
        denied=denied is not None,
        reasons=reasons,
    )


@dataclass(frozen=True)
class Sighting:
    """A lead as one query returned it (a lead returned by several queries has several)."""

    lead_id: uuid.UUID
    url: str
    title: str
    snippet: str
    query: str
    purpose: str | None
    # An EDGAR filing hit: the exact phrases the query's search matched in it. Empty: a web
    # result.
    matched: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankedLead:
    lead_id: uuid.UUID
    query: str  # the query of its best-scoring sighting
    score: LeadScore


def rank_leads(
    sightings: Sequence[Sighting],
    *,
    companies: Sequence[str],
    config: RankingConfig,
    company_sites: Sequence[str] = (),
) -> list[RankedLead]:
    """Each lead once, scored by its best sighting, highest first; ties keep the order the
    sightings are given in (the order found). Leads that aren't kept come after those that
    are, and denied hosts last."""
    best: dict[uuid.UUID, RankedLead] = {}
    for each in sightings:
        scored = score_lead(
            url=each.url,
            title=each.title,
            snippet=each.snippet,
            query=each.query,
            purpose=each.purpose,
            companies=companies,
            config=config,
            company_sites=company_sites,
            matched=each.matched,
        )
        held = best.get(each.lead_id)
        if held is None or (scored.kept, scored.score) > (held.score.kept, held.score.score):
            best[each.lead_id] = RankedLead(each.lead_id, each.query, scored)
    order = {lead_id: position for position, lead_id in enumerate(best)}
    return sorted(
        best.values(),
        key=lambda lead: (
            not lead.score.kept,
            lead.score.denied,
            -lead.score.score,
            order[lead.lead_id],
        ),
    )
