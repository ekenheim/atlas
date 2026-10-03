"""The behaviour checks: Memory, on Atlas's settings, does what Hindsight and the spec promise.

Each check runs against a **throwaway bank** that two companies' recorded documents (and the
synthetic call transcript) were retained into through Atlas's real retain path
(`tests/live/conformance.py` prepares it). Each names the documentation sentence or spec
decision it tests, and reports `passed` or `failed` with its evidence (IDs, counts).

A check whose behaviour is not on the branch yet reports `pending` with the ticket that builds
it, and fails nothing unless the run is strict. Whether it is on the branch is read from the
public shape the ticket describes: a field of the API's OpenAPI schema, a setting, the bank
template, or what the retain requests carry. Checks 1 to 9 were written against those shapes
before their tickets (03 to 10) were merged; check 10 runs today.

Every Hindsight request goes through the gateway; every Atlas read through `/api/v1`.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, JsonValue

from atlas.claims import LAYER_TERMS
from atlas.conformance.api import AtlasApi
from atlas.hindsight import HindsightGateway, HindsightNotFound, TagScope

Verdict = Literal["passed", "failed", "pending"]
type Evidence = dict[str, JsonValue]

# What a recall of the throwaway bank asks (check 10, and the queries of checks 6 and 9).
PROBE_QUERIES = (
    "indium phosphide laser capacity",
    "supply agreement with a customer",
    "revenue and demand outlook",
)
# The synthetic transcript's analyst question (tests/fixtures/tradingview/view-syn-view-1001-t)
# and words that attribute it to whoever asked it.
ANALYST_QUESTION_TERMS = ("largest customer",)
ATTRIBUTION_TERMS = ("analyst", "asked", "question")
# The company's own speakers in that transcript: a fact naming one of them reports their words
# (the CFO's answer repeats the question's words), not the analyst's question.
MANAGEMENT_SPEAKERS = ("alex example", "casey placeholder")
# Check 2: the share of a company's facts that must carry the filer's given entity (the lead's
# choice, 2026-10-03). The first live run (Hindsight 0.10.2) had it on 50 of Lumentum's 52 facts
# (96%) and 205 of Coherent's 208 (99%); the entity hop reads the facts that carry it.
ENTITY_COVERAGE = 0.95
# Check 9: a reflect citation Atlas labels unverified (its quote is not verbatim in the section)
# is allowed up to this share; a broken one never is.
UNVERIFIED_CITATIONS = 0.05


@dataclass
class BehaviourBank:
    """The throwaway bank and the Atlas that retained into it."""

    api: AtlasApi
    gateway: HindsightGateway
    theme: str
    companies: Mapping[str, str]  # slug -> company ID
    versions: Mapping[str, Mapping[str, str]]  # version ID -> {company, kind, url}
    retained_items: Callable[[], list[dict[str, Any]]]  # every retain item the bank was sent
    template: Mapping[str, Any]  # the bank template's manifest
    settings_fields: frozenset[str]  # the Settings fields this Atlas has
    drain: Callable[[], None]  # run the worker until the queue is empty
    enqueue: Callable[[str, str, dict[str, JsonValue]], None]  # (kind, key, payload)
    _openapi: dict[str, Any] | None = field(default=None, init=False)

    def openapi(self) -> dict[str, Any]:
        if self._openapi is None:
            self._openapi = self.api.openapi()
        return self._openapi

    @property
    def bank_id(self) -> str:
        return self.gateway.bank_id

    def theme_scope(self) -> TagScope:
        return TagScope([f"theme:{self.theme}"], "any_strict")

    def memory_documents(self) -> list[dict[str, Any]]:
        """Every memory document of the retained versions, with its version's company."""
        documents: list[dict[str, Any]] = []
        for version_id, info in self.versions.items():
            memory = self.api.get(f"/source-versions/{version_id}/memory")
            for document in cast(list[dict[str, Any]], memory["documents"]):
                documents.append(document | {"version_id": version_id, **info})
        return documents

    def recall(self, query: str, **fields: Any) -> dict[str, Any]:
        body = {"query": query, "scope": {"theme_ids": [self.theme]}, **fields}
        return cast(dict[str, Any], self.api.post("/memory/recall", body))


class CheckResult(BaseModel):
    number: int
    id: str
    ticket: str | None  # the ticket that builds the behaviour; None: built before this effort
    promise: str  # what is promised
    source: str  # the documentation sentence or spec decision it tests
    verdict: Verdict
    reason: str | None
    evidence: Evidence


@dataclass(frozen=True)
class Check:
    number: int
    id: str
    ticket: str | None
    promise: str
    source: str
    present: Callable[[BehaviourBank], bool]
    run: Callable[[BehaviourBank], tuple[bool, str | None, Evidence]]


def run_checks(bank: BehaviourBank, checks: Sequence[Check] | None = None) -> list[CheckResult]:
    """Run each check (None: all ten; an empty list: none) and return its result; a check
    that raises fails with the error, and an interrupt propagates."""
    results: list[CheckResult] = []
    for check in CHECKS if checks is None else checks:
        verdict: Verdict
        evidence: Evidence = {}
        reason: str | None
        try:
            if not check.present(bank):
                verdict, reason = "pending", f"pending: ticket {check.ticket}"
            else:
                passed, reason, evidence = check.run(bank)
                verdict = "passed" if passed else "failed"
        except Exception as error:  # a check that breaks is a failure, with its error
            verdict, reason = "failed", f"{type(error).__name__}: {error}"[:600]
        results.append(
            CheckResult(
                number=check.number,
                id=check.id,
                ticket=check.ticket,
                promise=check.promise,
                source=check.source,
                verdict=verdict,
                reason=reason,
                evidence=evidence,
            )
        )
    return results


# --- whether a behaviour is on the branch ---------------------------------------------------------


def _properties(openapi: Mapping[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    schemas = cast(dict[str, Any], openapi.get("components", {}).get("schemas", {}))
    for schema in schemas.values():
        properties = cast(dict[str, Any], cast(dict[str, Any], schema).get("properties") or {})
        for name, spec in properties.items():
            yield name, cast(dict[str, Any], spec)


def has_property(openapi: Mapping[str, Any], name: str) -> bool:
    """Whether any schema of the API has a property of this name."""
    return any(prop == name for prop, _ in _properties(openapi))


def has_enum_value(openapi: Mapping[str, Any], prop: str, value: str) -> bool:
    """Whether a property of this name (anywhere) allows this value."""
    schemas = cast(dict[str, Any], openapi.get("components", {}).get("schemas", {}))

    def values(spec: Mapping[str, Any]) -> list[Any]:
        found = list(cast(list[Any], spec.get("enum") or []))
        if "$ref" in spec:
            name = str(spec["$ref"]).rsplit("/", 1)[-1]
            found += values(cast(dict[str, Any], schemas.get(name, {})))
        for key in ("anyOf", "oneOf", "allOf"):
            for option in cast(list[dict[str, Any]], spec.get(key) or []):
                found += values(option)
        return found

    return any(name == prop and value in values(spec) for name, spec in _properties(openapi))


def _items_carry(bank: BehaviourBank, key: str) -> bool:
    return any(key in item for item in bank.retained_items())


def _template_has_label_group(bank: BehaviourBank, group: str) -> bool:
    labels = cast(list[dict[str, Any]], bank.template.get("bank", {}).get("entity_labels") or [])
    return any(label.get("key") == group for label in labels)


# --- 1: no section is lost silently (ticket 03) ---------------------------------------------------


def _sections_accounted(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    states: dict[str, int] = {}
    lost: list[JsonValue] = []
    for document in bank.memory_documents():
        state = str(document["retain_state"])
        states[state] = states.get(state, 0) + 1
        if state == "linked" or document.get("document_id") is None:
            continue
        try:
            stored: int | None = bank.gateway.get_document(
                str(document["document_id"])
            ).memory_unit_count
        except HindsightNotFound:
            stored = None
        problem = None
        if state == "completed" and not stored:
            problem = (
                "completed, but Hindsight holds no fact" if stored == 0 else "completed, absent"
            )
        elif state == "zero_fact" and stored != 0:
            problem = "zero-fact, but Hindsight holds facts" if stored else "zero-fact, absent"
        elif state in ("failed", "cancelled"):
            if stored:
                problem = f"{state}, but Hindsight stored it with {stored} facts"
            elif not document.get("error"):
                problem = f"{state} with no error recorded"
        elif state not in ("completed", "zero_fact"):
            problem = f"still {state} after the run settled"
        if problem is not None:
            lost.append(
                {
                    "version_id": str(document["version_id"]),
                    "section": str(document["section_anchor"]),
                    "state": state,
                    "hindsight_facts": stored,
                    "problem": problem,
                }
            )
    total = sum(states.values())
    evidence: Evidence = {"sections": total, "by_state": dict(states), "unaccounted": lost}
    if not total:
        return False, "no section was retained", evidence
    if lost:
        return False, f"{len(lost)} of {total} sections are not accounted for", evidence
    return True, None, evidence


# --- 2 and 3: what a retained section says (ticket 04) --------------------------------------------


def _entity_names(item: Mapping[str, Any]) -> list[str]:
    return [str(e.get("text")) for e in cast(list[dict[str, Any]], item.get("entities") or [])]


def _company_items(bank: BehaviourBank) -> dict[str, list[dict[str, Any]]]:
    """The retain items of each company's own documents (by the `company:` tag), one per
    document: a section sent again (a resubmit) is the same document, counted once."""
    by_company: dict[str, list[dict[str, Any]]] = {slug: [] for slug in bank.companies}
    ids = {company_id: slug for slug, company_id in bank.companies.items()}
    latest = {_doc_id(item): item for item in bank.retained_items()}
    for item in latest.values():
        for tag in cast(list[str], item.get("tags") or []):
            if tag.startswith("company:") and tag.removeprefix("company:") in ids:
                by_company[ids[tag.removeprefix("company:")]].append(item)
    return by_company


def _filer_names(bank: BehaviourBank) -> dict[str, str]:
    """Each company's canonical name: the entity every retain item of its own documents sends."""
    names: dict[str, str] = {}
    for slug, items in _company_items(bank).items():
        common: set[str] | None = None
        for item in items:
            sent = set(_entity_names(item))
            common = sent if common is None else common & sent
        if common and len(common) == 1:
            names[slug] = next(iter(common))
    return names


def _all_entities(bank: BehaviourBank) -> list[tuple[str, str, int]]:
    entities: list[tuple[str, str, int]] = []
    while True:
        page = bank.gateway.entities(limit=1000, offset=len(entities))
        entities += [(e.id, e.canonical_name, e.mention_count) for e in page.items]
        if not page.items or len(entities) >= page.total:
            return entities


def _one_entity_per_company(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    names = _filer_names(bank)
    entities = _all_entities(bank)
    facts = _fact_counts(bank)
    report: dict[str, JsonValue] = {}
    failures: list[str] = []
    for slug in bank.companies:
        name = names.get(slug)
        if name is None:
            failures.append(f"{slug}: its retain items share no one filer name")
            report[slug] = {"filer_name": None}
            continue
        exact = [(i, n, m) for i, n, m in entities if n == name]
        own = sum(facts.get(_doc_id(item), 0) for item in _company_items(bank)[slug])
        named_in_others = [
            item
            for other, items in _company_items(bank).items()
            if other != slug
            for item in items
            if name in _entity_names(item)
        ]
        others = sum(facts.get(_doc_id(item), 0) for item in named_in_others)
        mentions = exact[0][2] if len(exact) == 1 else None
        report[slug] = {
            "filer_name": name,
            "entities_with_that_name": len(exact),
            "mention_count": mentions,
            "facts_of_own_sections": own,
            "sections_of_others_naming_it": [_doc_id(item) for item in named_in_others],
            "facts_of_those_sections": others,
        }
        if len(exact) != 1:
            failures.append(f"{slug}: {len(exact)} entities named {name!r}")
        elif (mentions or 0) < ENTITY_COVERAGE * (own + others):
            failures.append(
                f"{slug}: {name!r} is on {mentions} facts; its own and the naming sections'"
                f" facts are {own + others} (at least {ENTITY_COVERAGE:.0%} must carry it)"
            )
    return not failures, "; ".join(failures) or None, {"companies": report}


def _doc_id(item: Mapping[str, Any]) -> str:
    return str(item["document_id"])


def _fact_counts(bank: BehaviourBank) -> dict[str, int]:
    return {
        str(d["document_id"]): int(d.get("fact_count") or 0)
        for d in bank.memory_documents()
        if d.get("document_id") and d["retain_state"] == "completed"
    }


def _analyst_question(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    transcripts = [
        d for d in bank.memory_documents() if d.get("kind") == "transcript" and d.get("document_id")
    ]
    if not transcripts:
        return False, "no call transcript was retained into the bank", {}
    items = {_doc_id(i): i for i in bank.retained_items()}
    examined = 0
    offending: list[JsonValue] = []
    contexts_without_analysts: list[str] = []
    for document in transcripts:
        document_id = str(document["document_id"])
        context = str(items.get(document_id, {}).get("context") or "")
        if "analyst" not in context.lower():
            contexts_without_analysts.append(document_id)
        for memory in bank.gateway.document_memories(document_id):
            examined += 1
            text = memory.text.lower()
            if (
                any(term in text for term in ANALYST_QUESTION_TERMS)
                and not any(word in text for word in ATTRIBUTION_TERMS)
                and not any(name in text for name in MANAGEMENT_SPEAKERS)
            ):
                offending.append({"memory_id": memory.id, "text": memory.text[:300]})
    evidence: Evidence = {
        "transcript_sections": [str(d["document_id"]) for d in transcripts],
        "facts_examined": examined,
        "contexts_not_naming_analysts": list[JsonValue](contexts_without_analysts),
        "analyst_question_as_company_statement": offending,
    }
    if contexts_without_analysts:
        return False, "a transcript section's context does not say analysts speak", evidence
    if offending:
        return False, f"{len(offending)} facts state the analyst's question unattributed", evidence
    return True, None, evidence


# --- 4: layer labels (ticket 05) -----------------------------------------------------------------


def _layer_labels(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    """A section counts when one of its own facts names a layer (a term of `LAYER_TERMS` in
    the fact's text, not merely somewhere in the section: a cover page or an exhibit list that
    mentions a product gives no fact about it); such a section fails when none of those facts
    carries a `layer:` label."""
    labelled: dict[str, int] = {}
    unlabelled: list[str] = []
    naming = 0
    for document in bank.memory_documents():
        if document["retain_state"] != "completed" or not document.get("document_id"):
            continue
        memories = bank.gateway.document_memories(str(document["document_id"]))
        naming_facts = [
            m
            for m in memories
            if any(t.lower() in m.text.lower() for terms in LAYER_TERMS.values() for t in terms)
        ]
        if not naming_facts:
            continue
        naming += 1
        tags = {t for m in naming_facts for t in m.tags if t.startswith("layer:")}
        if not tags:
            unlabelled.append(str(document["document_id"]))
        for tag in tags:
            labelled[tag] = labelled.get(tag, 0) + 1
    evidence: Evidence = {
        "sections_naming_a_layer": naming,
        "sections_with_labelled_facts_by_label": dict(labelled),
        "sections_naming_a_layer_without_a_label": list[JsonValue](unlabelled),
    }
    if not naming:
        return False, "no retained section names a layer", evidence
    if unlabelled:
        return False, f"{len(unlabelled)} sections name a layer and carry no label", evidence
    label = max(labelled, key=lambda tag: labelled[tag])
    recalled = bank.gateway.recall(PROBE_QUERIES[0], scope=TagScope([label], "any_strict"))
    off = [m.id for m in recalled.memories if label not in m.tags]
    evidence["recall_by_label"] = {
        "label": label,
        "returned": len(recalled.memories),
        "without_the_label": list[JsonValue](off),
    }
    if not recalled.memories:
        return False, f"a recall filtered by {label} returned nothing", evidence
    if off:
        return False, f"a recall filtered by {label} returned {len(off)} unlabelled", evidence
    return True, None, evidence


# --- 5: observation scopes (ticket 06) ------------------------------------------------------------


def _observation_scopes(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    page = bank.gateway.observation_scopes()
    theme_tag = f"theme:{bank.theme}"
    scopes: list[JsonValue] = [
        {"tags": list[JsonValue](s.tags), "count": s.count} for s in page.scopes
    ]
    theme_count = sum(s.count for s in page.scopes if s.tags == [theme_tag])
    spanning: list[JsonValue] = []
    company_ids = set(bank.companies.values())
    for query in PROBE_QUERIES:
        for memory in cast(list[dict[str, Any]], bank.recall(query)["memories"]):
            if memory["type"] != "observation":
                continue
            sources = cast(list[dict[str, Any]], memory["provenance"]["sources"])
            companies = {str(s["company_id"]) for s in sources if s.get("company_id")}
            if company_ids <= companies:
                spanning.append({"memory_id": memory["memory_id"], "sources": len(sources)})
    evidence: Evidence = {
        "scopes": scopes,
        "observations_in_theme_scope": theme_count,
        "observations_drawing_on_both_companies": spanning,
    }
    # The promise is the scope: every observation in the theme's scope alone. Whether one draws
    # on both companies is the observations mission's call (it keeps one observation per company
    # and subject), so it is evidence, not a verdict.
    outside = [s for s in page.scopes if s.tags != [theme_tag]]
    if not theme_count:
        return False, f"no observation in the scope [{theme_tag}]", evidence
    if outside:
        stray = sum(s.count for s in outside)
        return False, f"{stray} observations outside the scope [{theme_tag}]", evidence
    return True, None, evidence


# --- 6: recall as a reading index (ticket 07) -----------------------------------------------------


def _recall_options(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    failures: list[str] = []
    query = PROBE_QUERIES[0]
    preferred = bank.recall(query, prefer_observations=True, types=["world", "observation"])
    memories = cast(list[dict[str, Any]], preferred["memories"])
    sources_of_observations = {
        str(source.get("memory_id"))
        for m in memories
        if m["type"] == "observation"
        for source in cast(list[dict[str, Any]], m["provenance"]["sources"])
    }
    duplicated = [
        m["memory_id"]
        for m in memories
        if m["type"] != "observation" and m["memory_id"] in sources_of_observations
    ]
    if duplicated:
        failures.append(f"{len(duplicated)} facts beside the observation built from them")
    early = bank.recall(query, query_timestamp="2020-01-01T00:00:00Z")
    late = bank.recall(query, query_timestamp=datetime.now(UTC).isoformat())
    order = [
        [m["memory_id"] for m in cast(list[dict[str, Any]], a["memories"])] for a in (early, late)
    ]
    if order[0] == order[1]:
        failures.append("query_timestamp moved nothing")
    small = bank.recall(query, max_tokens=256)
    large = bank.recall(query, max_tokens=8192)
    counts = [len(cast(list[Any], a["memories"])) for a in (small, large)]
    if counts[1] <= counts[0]:
        failures.append(f"max_tokens 8192 returned {counts[1]}, 256 returned {counts[0]}")
    evidence: Evidence = {
        "prefer_observations": {
            "returned": len(memories),
            "observations": sum(1 for m in memories if m["type"] == "observation"),
            "facts_beside_their_observation": list[JsonValue](duplicated),
        },
        "query_timestamp": {
            "2020-01-01": list[JsonValue](order[0]),
            "now": list[JsonValue](order[1]),
        },
        "max_tokens": {"256": counts[0], "8192": counts[1]},
    }
    return not failures, "; ".join(failures) or None, evidence


# --- 7: chunk-exact pointers (ticket 08) ----------------------------------------------------------


def _chunks_located(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    located = 0
    missing: list[JsonValue] = []
    facts = 0
    for document in bank.memory_documents():
        if document["retain_state"] != "completed" or not document.get("document_id"):
            continue
        parsed = bank.api.text(f"/source-versions/{document['version_id']}/content", kind="parsed")
        section = parsed[int(document["char_start"]) : int(document["char_end"])]
        chunks = {c.chunk_id: c for c in bank.gateway.document_chunks(str(document["document_id"]))}
        cursor = 0
        spans: dict[str, int] = {}
        for chunk in sorted(chunks.values(), key=lambda c: c.chunk_index):
            at = section.find(chunk.chunk_text, cursor)
            if at >= 0:
                spans[chunk.chunk_id] = at
                cursor = at + len(chunk.chunk_text)
        for memory in bank.gateway.document_memories(str(document["document_id"])):
            facts += 1
            if memory.chunk_id in spans:
                located += 1
            else:
                missing.append(
                    {
                        "memory_id": memory.id,
                        "chunk_id": memory.chunk_id,
                        "section": str(document["section_anchor"]),
                    }
                )
    evidence: Evidence = {"facts": facts, "placed_by_chunk": located, "not_placed": missing}
    if not facts:
        return False, "no fact to place", evidence
    if missing:
        return (
            False,
            f"{len(missing)} facts' chunks do not occur verbatim in their section",
            evidence,
        )
    return True, None, evidence


# --- 8: the entity hop (ticket 09) ----------------------------------------------------------------


def _entity_hop(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    names = _filer_names(bank)
    entities = {name: entity_id for entity_id, name, _ in _all_entities(bank)}
    report: dict[str, JsonValue] = {}
    failures: list[str] = []
    expected_any = False
    for slug, name in names.items():
        expected = sorted(
            {
                _doc_id(item)
                for other, items in _company_items(bank).items()
                if other != slug
                for item in items
                if name in _entity_names(item)
            }
        )
        if not expected:
            continue
        expected_any = True
        if name not in entities:
            failures.append(f"{slug}: no entity named {name!r}")
            continue
        listed = bank.gateway.entity_memories(entities[name], scope=bank.theme_scope())
        found = sorted({m.document_id for m in listed if m.document_id in expected})
        report[slug] = {
            "entity": name,
            "facts_listed": len(listed),
            "other_sections_naming_it": list[JsonValue](expected),
            "found": list[JsonValue](found),
        }
        if found != expected:
            failures.append(f"{slug}: the lookup missed {len(expected) - len(found)} sections")
    if not expected_any:
        return False, "no retained section names another company of the bank", {"companies": report}
    return not failures, "; ".join(failures) or None, {"companies": report}


# --- 9: reflect and the mental models (ticket 10) -------------------------------------------------


def _reflect_grounded(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    failures: list[str] = []
    triggers = {
        str(m.get("id")): cast(dict[str, Any], m.get("trigger") or {})
        for m in cast(list[dict[str, Any]], bank.template.get("mental_models") or [])
    }
    reading_models = [i for i, t in triggers.items() if t.get("exclude_mental_models") is not True]
    if reading_models:
        failures.append(f"models whose refresh may read other models: {', '.join(reading_models)}")
    accepted = bank.api.post(
        "/memory/reflect",
        {
            "question": "Which suppliers are capacity-constrained?",
            "scope": {"theme_ids": [bank.theme]},
            "budget": "mid",
            "exclude_mental_models": True,
        },
    )
    bank.drain()
    answer = bank.api.get(f"/memory/reflect/{accepted['research_answer']['id']}")
    citations = cast(list[dict[str, Any]], answer.get("citations") or [])
    unresolved = [c for c in citations if c.get("state") != "resolved"]
    broken = [c for c in unresolved if c.get("state") == "broken"]
    if answer.get("status") != "completed":
        failures.append(f"the reflect ended {answer.get('status')}: {answer.get('error')}")
    elif not citations:
        failures.append("the reflect cited nothing")
    elif broken:
        failures.append(f"{len(broken)} of {len(citations)} citations are broken")
    elif len(unresolved) > UNVERIFIED_CITATIONS * len(citations):
        failures.append(f"{len(unresolved)} of {len(citations)} citations do not resolve")
    refreshed: dict[str, JsonValue] = {}
    for model_id in triggers:
        bank.enqueue(
            "refresh_mental_model", f"conformance:{model_id}", {"mental_model_id": model_id}
        )
        bank.drain()
        model = bank.api.get(f"/mental-models/{model_id}")
        model_citations = cast(list[dict[str, Any]], model.get("citations") or [])
        of_models = [c for c in model_citations if c.get("kind") == "mental_model"]
        refreshed[model_id] = {
            "last_refreshed_at": model.get("last_refreshed_at"),
            "citations": len(model_citations),
            "of_mental_models": len(of_models),
        }
        if of_models:
            failures.append(f"model {model_id} cites another model")
    evidence: Evidence = {
        "reflect": {
            "status": answer.get("status"),
            "citations": len(citations),
            "unresolved": [{"state": c.get("state"), "kind": c.get("kind")} for c in unresolved],
        },
        "models": refreshed,
    }
    return not failures, "; ".join(failures) or None, evidence


# --- 10: every citation of a recall resolves ------------------------------------------------------


def _citations_resolve(bank: BehaviourBank) -> tuple[bool, str | None, Evidence]:
    counts: dict[str, int] = {}
    not_resolved: list[JsonValue] = []
    for query in PROBE_QUERIES:
        for memory in cast(list[dict[str, Any]], bank.recall(query)["memories"]):
            state = str(memory["provenance"]["state"])
            counts[state] = counts.get(state, 0) + 1
            if state != "resolved":
                not_resolved.append(
                    {
                        "query": query,
                        "memory_id": memory["memory_id"],
                        "state": state,
                        "reason": memory["provenance"].get("reason"),
                    }
                )
    total = sum(counts.values())
    evidence: Evidence = {
        "recalls": len(PROBE_QUERIES),
        "memories": total,
        "by_state": dict(counts),
        "not_resolved": not_resolved,
    }
    if not total:
        return False, "the recalls returned nothing", evidence
    if not_resolved:
        return False, f"{len(not_resolved)} of {total} citations do not resolve", evidence
    return True, None, evidence


CHECKS: tuple[Check, ...] = (
    Check(
        1,
        "no-section-lost",
        "03",
        "Every retained section has facts or is reported empty; none is lost silently.",
        "Spec, 'Intake that doesn't lose sections': a section's outcome is read from its own"
        " Hindsight document whatever the operation's end state: stored with facts is"
        " completed, stored with none is zero-fact, absent is failed.",
        lambda bank: has_enum_value(bank.openapi(), "retain_state", "cancelled"),
        _sections_accounted,
    ),
    Check(
        2,
        "one-entity-per-company",
        "04",
        "The filer is one entity across its documents, and a company named in another's"
        " document is the same entity.",
        "Spec, 'What a retained section says': the item's entities are the filer's canonical"
        " name and the universe companies the section names, sent with resolve_entities false;"
        " feature matrix: a given entity is on every fact of its item, as written.",
        lambda bank: _items_carry(bank, "entities"),
        _one_entity_per_company,
    ),
    Check(
        3,
        "analyst-question-not-company-statement",
        "04",
        "A call transcript's analyst question is not stored as the company's statement.",
        "Spec, 'What a retained section says': for a call transcript, the context says that"
        " management and analysts speak and an analyst's question is not the company's"
        " statement.",
        lambda bank: _items_carry(bank, "entities"),
        _analyst_question,
    ),
    Check(
        4,
        "layer-labels",
        "05",
        "Facts carry a layer label where the text names a layer, and a recall filtered by the"
        " label returns only those.",
        "Hindsight docs (entity labels): a label group with tag: true writes its values as"
        " tags; spec, 'The bank template': one group for the supply-chain layer.",
        lambda bank: _template_has_label_group(bank, "layer"),
        _layer_labels,
    ),
    Check(
        5,
        "observation-scopes",
        "06",
        "After consolidation an observation exists in the theme's scope whose sources lie in"
        " both companies' documents.",
        "Spec, 'Observation scopes': each retain item sends one explicit scope per theme"
        " (ticket 06 dropped the company scope after ticket 01 measured its cost).",
        lambda bank: _items_carry(bank, "observation_scopes"),
        _observation_scopes,
    ),
    Check(
        6,
        "recall-as-reading-index",
        "07",
        "A recall with prefer_observations returns no fact an observation in the same answer"
        " was built from; query_timestamp moves recency; a larger max_tokens returns more.",
        "Hindsight docs (recall): prefer_observations, query_timestamp and max_tokens; feature"
        " matrix rows of the same names (0.10.2, verified).",
        lambda bank: has_property(bank.openapi(), "prefer_observations"),
        _recall_options,
    ),
    Check(
        7,
        "chunk-exact-pointer",
        "08",
        "A pointer placed by its chunk lands on the passage the fact came from: every fact's"
        " chunk occurs verbatim in its section.",
        "Feature matrix (b): a chunk is a verbatim slice of the retained content, offsets had"
        " by searching in chunk_index order; spec, 'Chunk-exact pointers'.",
        lambda bank: has_property(bank.openapi(), "placed_by"),
        _chunks_located,
    ),
    Check(
        8,
        "entity-hop",
        "09",
        "The entity lookup returns the other company's section that names the filer.",
        "Spec, 'The entity hop': Atlas lists the theme's facts that carry a company's entity"
        " and come from another company's documents (the memory list by entity_id).",
        lambda bank: "entity_hop_max_companies" in bank.settings_fields,
        _entity_hop,
    ),
    Check(
        9,
        "reflect-grounded",
        "10",
        "A reflect cites only memories that resolve to sections, and a refresh of a model"
        " reads no other model.",
        "Spec, 'Reflect and the mental models': reflect sends exclude_mental_models when"
        " citations must resolve; the model triggers gain exclude_mental_models: true.",
        lambda bank: has_property(bank.openapi(), "exclude_mental_models"),
        _reflect_grounded,
    ),
    Check(
        10,
        "citations-resolve",
        None,
        "Every citation of a recall resolves; none is broken.",
        "docs/decisions.md, provenance: every cited memory resolves to a Source Version"
        " section through its document_id and Atlas's metadata (feature matrix, 'Differences"
        " that change Atlas's design' 1).",
        lambda bank: True,
        _citations_resolve,
    ),
)
