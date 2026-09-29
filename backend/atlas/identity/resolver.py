"""The Entity Resolver: a company mention → a legal entity, its identifiers and its listings.

A deterministic pipeline over SEC, GLEIF and OpenFIGI (docs/research/identity-apis.md §4,
branch `research/identity-apis`). Every identifier it would map is a `Proposal` with a tier:

- `exact`: reached through a strong identifier (CIK, LEI, ISIN, or a ticker on a known
  venue) and every other supplied identifier agrees
- `corroborated`: two registries joined on name + jurisdiction. That is the only way a CIK
  meets an LEI (no source links them), so it is always left for the owner to confirm
- `candidate`: name-only, single-source, a ticker without a venue, an ADR, more than one
  surviving match, or anything else that needs a human
- `conflict`: two sources disagree (e.g. an ISIN's issuer isn't the CIK's company). Nothing
  is proposed; both chains are returned as candidates

Only exact and corroborated proposals commit automatically, and a CIK↔LEI link never does
(`Proposal.auto_commit`). Names are equal only after `normalize_name`, never by similarity.
The resolver never writes: `atlas.identity.service` looks up the universe first and stores
what it proposes.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from atlas.identity.gleif import GleifClient, LeiRecord
from atlas.identity.normalize import (
    MIC_CURRENCY,
    SEC_EXCHANGE_MIC,
    SEGMENTS,
    US_MICS,
    US_STATES,
    canonical_ticker,
    normalize_cik,
    normalize_name,
    operating_mic,
    segment_mics,
    valid_isin,
    valid_lei,
)
from atlas.identity.openfigi import Figi, MappingJob, MappingResult, OpenFigiClient
from atlas.identity.sec import SecEntity, SecIdentityClient
from atlas.settings import Settings

type Tier = Literal["exact", "corroborated", "candidate", "conflict", "unresolved"]
type ProposalTier = Literal["exact", "corroborated", "candidate"]
type Source = Literal["sec", "gleif", "openfigi", "atlas"]
_RANK: dict[str, int] = {"exact": 0, "corroborated": 1, "candidate": 2, "conflict": 3}
# LEI registration states that no longer identify a live entity on their own.
_REVIEW_LEI_STATUSES = frozenset({"RETIRED", "MERGED", "DUPLICATE", "ANNULLED", "TRANSFERRED"})


_BY_RANK: tuple[ProposalTier, ...] = ("exact", "corroborated", "candidate")


def _worst(*tiers: str) -> ProposalTier:
    return _BY_RANK[max(_RANK[tier] for tier in tiers)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Mention(_Frozen):
    """What a source said about a company. Any field may be missing; `mic` may be an
    operating (XNAS) or segment (XNGS) MIC; `as_of` bounds historical names and listings."""

    name: str | None = None
    ticker: str | None = None
    mic: str | None = None
    cik: str | None = None
    lei: str | None = None
    isin: str | None = None
    country: str | None = Field(default=None, description="ISO 3166-1 alpha-2")
    as_of: date | None = None


class Fact(_Frozen):
    """One external fact the resolution used: where it came from and when it was read."""

    source: Source
    url: str
    observed_at: datetime
    statement: str


class Alias(_Frozen):
    name: str
    kind: Literal["legal", "former", "other"]
    valid_from: date | None = None
    valid_to: date | None = None
    source: Source


class Listing(_Frozen):
    ticker: str
    exchange_mic: str  # ISO 10383 operating MIC
    segment_mic: str | None  # the segment OpenFIGI matched (XNGS), when one did
    figi: str | None  # composite (country-level) FIGI; survives a ticker change
    share_class_figi: str | None
    instrument_type: str  # common, adr, ...
    security_type2: str | None
    currency: str | None  # from the venue; OpenFIGI returns none
    figi_name: str | None


class Entity(_Frozen):
    name: str
    cik: str | None = None
    lei: str | None = None
    lei_status: str | None = None
    jurisdiction: str | None = None  # GLEIF's, e.g. US-PA
    state_of_incorporation: str | None = None  # SEC's, e.g. PA
    aliases: list[Alias] = []
    listings: list[Listing] = []


class Proposal(_Frozen):
    """One identifier mapping the resolution supports: `cik`, `lei`, or a `listing`
    (value `TICKER@MIC`, the listing's fields in `details`)."""

    kind: Literal["cik", "lei", "listing"]
    value: str
    tier: ProposalTier
    source: Source
    url: str
    observed_at: datetime
    owner_confirmation: bool  # a CIK↔LEI link: only the owner commits it
    reasons: list[str] = []
    details: dict[str, Any] = {}

    @property
    def auto_commit(self) -> bool:
        return self.tier in ("exact", "corroborated") and not self.owner_confirmation


class Resolution(_Frozen):
    mention: Mention
    tier: Tier
    entity: Entity | None
    candidates: list[Entity]
    proposals: list[Proposal]
    review_reasons: list[str]
    notes: list[str]
    evidence: list[Fact]
    dropped: list[str]  # invalid identifiers, dropped rather than repaired
    # Set by `atlas.identity.service.resolve_mention`: the universe company it matched.
    company_id: str | None = None
    matched_by: str | None = None


@dataclass
class _Run:
    now: datetime
    evidence: list[Fact] = field(default_factory=list[Fact])
    reasons: list[str] = field(default_factory=list[str])
    notes: list[str] = field(default_factory=list[str])
    dropped: list[str] = field(default_factory=list[str])

    def fact(self, source: Source, url: str, statement: str) -> None:
        self.evidence.append(
            Fact(source=source, url=url, observed_at=self.now, statement=statement)
        )


def _names_agree(left: tuple[str, ...] | list[str], right: tuple[str, ...] | list[str]) -> bool:
    ours = {normalize_name(n) for n in left if n}
    return any(normalize_name(n) in ours for n in right if n)


def _jurisdiction_agrees(state: str | None, country: str | None, gleif: str | None) -> bool | None:
    """SEC's state of incorporation (or, for a non-US issuer, the known country) against
    GLEIF's jurisdiction; None when they can't be compared."""
    if not gleif:
        return None
    if state in US_STATES:
        return gleif == f"US-{state}"
    if country:
        return gleif.split("-", 1)[0] == country
    return None


def _sec_names(entity: SecEntity, as_of: date | None) -> list[str]:
    names = [entity.name]
    for former in entity.former_names:
        if as_of is None or (
            (former.valid_from is None or former.valid_from <= as_of)
            and (former.valid_to is None or as_of < former.valid_to)
        ):
            names.append(former.name)
    return names


def _sec_aliases(entity: SecEntity) -> list[Alias]:
    return [Alias(name=entity.name, kind="legal", source="sec")] + [
        Alias(
            name=f.name, kind="former", valid_from=f.valid_from, valid_to=f.valid_to, source="sec"
        )
        for f in entity.former_names
    ]


def _gleif_aliases(record: LeiRecord) -> list[Alias]:
    return [Alias(name=record.legal_name, kind="legal", source="gleif")] + [
        Alias(name=name, kind="other", source="gleif") for name in record.other_names
    ]


def _lei_details(record: LeiRecord) -> dict[str, Any]:
    return {
        "legal_name": record.legal_name,
        "other_names": list(record.other_names),
        "jurisdiction": record.jurisdiction,
        "registration_status": record.registration_status,
        "entity_status": record.entity_status,
    }


def _lei_entity(record: LeiRecord) -> Entity:
    return Entity(
        name=record.legal_name,
        lei=record.lei,
        lei_status=record.registration_status,
        jurisdiction=record.jurisdiction,
        aliases=_gleif_aliases(record),
    )


def _instrument_type(figi: Figi) -> str:
    if figi.depositary_receipt:
        return "adr"
    if figi.security_type2 == "Common Stock":
        return "common"
    return (figi.security_type2 or figi.security_type or "unknown").lower().replace(" ", "_")


class EntityResolver:
    def __init__(
        self,
        sec: SecIdentityClient,
        gleif: GleifClient,
        openfigi: OpenFigiClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sec = sec
        self.gleif = gleif
        self.openfigi = openfigi
        self._clock = clock

    @classmethod
    @contextmanager
    def from_settings(
        cls,
        settings: Settings,
        *,
        transport: httpx2.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> Generator["EntityResolver"]:
        """The resolver over the configured sources (one transport for all three in tests).
        SEC needs `ATLAS_SEC_USER_AGENT`."""
        if not settings.sec_user_agent:
            raise ValueError("entity resolution calls SEC: set ATLAS_SEC_USER_AGENT")
        sec = SecIdentityClient(
            settings.sec_user_agent,
            files_url=settings.sec_files_url,
            data_url=settings.sec_data_url,
            transport=transport,
        )
        gleif = GleifClient(settings.gleif_url, transport=transport)
        openfigi = OpenFigiClient(settings.openfigi_url, transport=transport)
        try:
            yield cls(sec, gleif, openfigi, **({} if clock is None else {"clock": clock}))
        finally:
            sec.close()
            gleif.close()
            openfigi.close()

    # --- the pipeline ---

    def resolve(
        self, mention: Mention, *, ignored_ciks: frozenset[str] = frozenset()
    ) -> Resolution:
        run = _Run(self._clock())
        cik, lei, isin, ticker, mic = self._validate(mention, run)
        if cik in ignored_ciks:
            run.dropped.append(f"CIK {cik} is an ignored (unsponsored-ADR) CIK")
            cik = None
        as_of = mention.as_of

        # Strong identifiers, one registry each.
        sec_entity: SecEntity | None = None
        cik_tier: ProposalTier = "exact"
        cik_owner = False
        if cik is not None:
            sec_entity = self._submissions(cik, run)
        lei_record = self._lei_record(lei, run) if lei else None
        isin_record: LeiRecord | None = None
        isin_figi: Figi | None = None
        isin_listing: Listing | None = None
        if isin is not None:
            isin_record, isin_figi = self._by_isin(isin, run)
            if isin_figi is not None and mic is not None and ticker is None:
                isin_listing = self._listing(isin_figi.ticker, mic, run)

        ticker_listing: Listing | None = None
        if ticker is not None:
            ticker_cik, ticker_tier = self._ticker_cik(ticker, mic, run, ignored_ciks)
            if ticker_cik is not None:
                if sec_entity is not None and sec_entity.cik != ticker_cik:
                    return self._conflict(
                        mention,
                        run,
                        f"ticker {ticker} is CIK {ticker_cik} at SEC, not CIK {sec_entity.cik}",
                        [self._sec_entity_view(sec_entity)],
                    )
                if sec_entity is None:
                    sec_entity = self._submissions(ticker_cik, run)
                    cik_tier = ticker_tier
            if mic is not None:
                ticker_listing = self._listing(ticker, mic, run)

        if sec_entity is not None and sec_entity.adr_shell:
            run.reasons.append(
                f"CIK {sec_entity.cik} holds only depositary F-6 filings (an unsponsored-ADR"
                " shell), not the issuer's reports"
            )
            candidates = [self._sec_entity_view(sec_entity)]
            sec_entity = None
            if lei_record is None and isin_record is None:
                return self._finish(mention, run, None, candidates, [], review=True)

        # Two LEIs from two identifiers must agree.
        if lei_record is not None and isin_record is not None and lei_record.lei != isin_record.lei:
            return self._conflict(
                mention,
                run,
                f"ISIN {isin}'s issuer is LEI {isin_record.lei}, not {lei_record.lei}",
                [_lei_entity(lei_record), _lei_entity(isin_record)],
            )
        gleif_record = lei_record or isin_record
        lei_from_identifier = gleif_record is not None

        # Cross-registry: a CIK and an LEI reached independently must be the same entity.
        if sec_entity is not None and gleif_record is not None:
            names = _sec_names(sec_entity, None)
            if not _names_agree(names, list(gleif_record.names)):
                return self._conflict(
                    mention,
                    run,
                    f"CIK {sec_entity.cik} is {sec_entity.name!r} at SEC, but LEI"
                    f" {gleif_record.lei} is {gleif_record.legal_name!r} at GLEIF",
                    [self._sec_entity_view(sec_entity), _lei_entity(gleif_record)],
                )
        isin_composite = isin_figi.composite_figi or isin_figi.figi if isin_figi else None
        if isin_composite and ticker_listing is not None and isin_composite != ticker_listing.figi:
            return self._conflict(
                mention,
                run,
                f"ISIN {isin} is FIGI {isin_composite}, but {ticker} on {mic} is"
                f" {ticker_listing.figi}",
                [],
            )
        if isin_figi is not None and isin_figi.depositary_receipt:
            run.reasons.append(
                f"ISIN {isin} is a depositary receipt: confirm the underlying issuer and the ratio"
            )

        proposals: list[Proposal] = []
        candidates: list[Entity] = []

        # Link the missing registry by name + jurisdiction.
        lei_candidates: list[LeiRecord] = []
        if sec_entity is not None and gleif_record is None:
            gleif_record, lei_candidates = self._lei_for(sec_entity, mention, run)
        elif gleif_record is not None and sec_entity is None and cik is None:
            linked = self._cik_for(gleif_record, mention, run, ignored_ciks)
            if linked is not None:
                sec_entity, cik_tier = linked
                cik_owner = True

        if sec_entity is None and gleif_record is None:
            if ticker_listing is not None or isin_listing is not None:
                run.reasons.append("a listing was found but no issuer registry record")
                listing = ticker_listing or isin_listing
                assert listing is not None
                entity = Entity(name=listing.figi_name or listing.ticker, listings=[listing])
                return self._finish(mention, run, entity, [], [], review=True)
            if mention.name:
                return self._by_name(mention, run, ignored_ciks)
            return self._finish(mention, run, None, [], [])

        # The mentioned name must be one of the entity's names.
        known_names: list[str] = []
        if sec_entity is not None:
            known_names += _sec_names(sec_entity, as_of)
        if gleif_record is not None:
            known_names += list(gleif_record.names)
        name_ok = mention.name is None or _names_agree(known_names, [mention.name])
        if not name_ok:
            run.reasons.append(f"the mentioned name {mention.name!r} is none of the entity's names")

        if sec_entity is not None:
            tier = cik_tier if name_ok else "candidate"
            proposals.append(
                Proposal(
                    kind="cik",
                    value=sec_entity.cik,
                    tier=tier,
                    source="sec",
                    url=sec_entity.url,
                    observed_at=run.now,
                    owner_confirmation=cik_owner or tier == "candidate",
                    reasons=[] if tier != "candidate" else list(run.reasons),
                    details={"name": sec_entity.name},
                )
            )
        if gleif_record is not None:
            proposals.append(
                self._lei_proposal(
                    gleif_record,
                    run,
                    linked_by_name=not lei_from_identifier,
                    sec_entity=None if cik_owner else sec_entity,
                    mention=mention,
                    name_ok=name_ok,
                )
            )
        for record in lei_candidates:
            proposals.append(
                Proposal(
                    kind="lei",
                    value=record.lei,
                    tier="candidate",
                    source="gleif",
                    url=record.url,
                    observed_at=run.now,
                    owner_confirmation=True,
                    reasons=["one of several GLEIF matches for the name"],
                    details=_lei_details(record),
                )
            )
            run.fact("gleif", record.url, f"name {sec_entity.name!r}: {record.legal_name!r}")  # pyright: ignore[reportOptionalMemberAccess]
            candidates.append(_lei_entity(record))

        # Listings: the mentioned one, else the SEC's current ones.
        listings: list[Listing] = []
        for listing in (ticker_listing, isin_listing):
            if listing is not None and all(listing.figi != known.figi for known in listings):
                listings.append(listing)
        if not listings and sec_entity is not None:
            for sec_ticker, label in zip(sec_entity.tickers, sec_entity.exchanges, strict=False):
                venue = SEC_EXCHANGE_MIC.get(label or "")
                if venue is None:
                    run.notes.append(f"SEC lists {sec_ticker} on {label or 'no exchange'}: skipped")
                    continue
                found = self._listing(sec_ticker, venue, run)
                if found is not None:
                    listings.append(found)
        issuer_tier: ProposalTier = cik_tier if sec_entity is not None else "exact"
        for listing in listings:
            proposals.append(self._listing_proposal(listing, known_names, issuer_tier, run))

        entity = Entity(name="")
        if gleif_record is not None:
            entity = _lei_entity(gleif_record)
        if sec_entity is not None:
            entity = self._sec_entity_view(sec_entity).model_copy(
                update={
                    "lei": entity.lei,
                    "lei_status": entity.lei_status,
                    "jurisdiction": entity.jurisdiction,
                    "aliases": _sec_aliases(sec_entity) + entity.aliases,
                }
            )
        entity = entity.model_copy(update={"listings": listings})
        # Any review reason (an ADR, a venue mismatch, ambiguous GLEIF matches) needs a human.
        review = not name_ok or bool(run.reasons)
        return self._finish(mention, run, entity, candidates, proposals, review=review)

    # --- steps ---

    def _validate(
        self, mention: Mention, run: _Run
    ) -> tuple[str | None, str | None, str | None, str | None, str | None]:
        cik = None
        if mention.cik:
            cik = normalize_cik(mention.cik)
            if cik is None:
                run.dropped.append(f"CIK {mention.cik!r} is not 1-10 digits")
        lei = mention.lei.strip().upper() if mention.lei else None
        if lei is not None and not valid_lei(lei):
            run.dropped.append(f"LEI {mention.lei!r} fails the ISO 17442 check")
            lei = None
        isin = mention.isin.strip().upper() if mention.isin else None
        if isin is not None and not valid_isin(isin):
            run.dropped.append(f"ISIN {mention.isin!r} fails the ISO 6166 check digit")
            isin = None
        ticker = canonical_ticker(mention.ticker) if mention.ticker else None
        mic = mention.mic.strip().upper() if mention.mic else None
        if mic is not None and not (len(mic) == 4 and mic.isalnum()):
            run.dropped.append(f"MIC {mention.mic!r} is not an ISO 10383 code")
            mic = None
        return cik, lei, isin, ticker, mic

    def _submissions(self, cik: str, run: _Run) -> SecEntity | None:
        entity = self.sec.submissions(cik)
        if entity is None:
            run.dropped.append(f"SEC has no CIK {cik}")
            return None
        run.fact("sec", entity.url, f"CIK {cik} is {entity.name!r}")
        return entity

    def _lei_record(self, lei: str, run: _Run) -> LeiRecord | None:
        record = self.gleif.record(lei)
        if record is None:
            run.dropped.append(f"GLEIF has no LEI {lei}")
            return None
        run.fact(
            "gleif",
            record.url,
            f"LEI {lei} is {record.legal_name!r} ({record.registration_status})",
        )
        return record

    def _by_isin(self, isin: str, run: _Run) -> tuple[LeiRecord | None, Figi | None]:
        """ISIN → the issuer's LEI (GLEIF; an ADR's ISIN gives the underlying issuer) and,
        for a US ISIN, its composite FIGI (OpenFIGI, country composite `US`)."""
        issuers = self.gleif.by_isin(isin)
        record: LeiRecord | None = None
        if len(issuers) == 1:
            record = issuers[0]
            run.fact("gleif", record.url, f"ISIN {isin}'s issuer is LEI {record.lei}")
        elif len(issuers) > 1:
            run.reasons.append(f"GLEIF maps ISIN {isin} to {len(issuers)} issuers")
        row: Figi | None = None
        if isin.startswith("US"):
            [result] = self.openfigi.map([MappingJob("ID_ISIN", isin, exch_code="US")])
            self._record_mapping([result], run)
            row = result.figis[0] if len(result.figis) == 1 else None
        return record, row

    def _ticker_cik(
        self, ticker: str, mic: str | None, run: _Run, ignored: frozenset[str]
    ) -> tuple[str | None, ProposalTier]:
        """The CIK SEC's ticker file gives `ticker` on `mic` (US venues only)."""
        if mic is not None and operating_mic(mic) not in US_MICS:
            return None, "exact"
        rows = [row for row in self.sec.by_ticker(ticker) if row.cik not in ignored]
        if not rows:
            return None, "exact"
        [row, *more] = rows
        run.fact("sec", self.sec.tickers_url, f"{ticker} is CIK {row.cik} ({row.exchange})")
        if more:
            run.reasons.append(f"SEC maps {ticker} to {len(rows)} CIKs")
            return None, "candidate"
        if mic is None:
            run.reasons.append(f"ticker {ticker} came without a venue")
            return row.cik, "candidate"
        venue = SEC_EXCHANGE_MIC.get(row.exchange or "")
        if venue != operating_mic(mic):
            run.reasons.append(f"SEC lists {ticker} on {row.exchange or 'no exchange'}, not {mic}")
            return row.cik, "candidate"
        return row.cik, "exact"

    def _listing(self, ticker: str, mic: str, run: _Run) -> Listing | None:
        operating = operating_mic(mic)
        segments = segment_mics(mic) if mic == operating else (mic,)
        composite_job = (
            MappingJob("TICKER", ticker, exch_code="US") if operating in US_MICS else None
        )
        jobs = ([composite_job] if composite_job else []) + [
            MappingJob("TICKER", ticker, mic_code=segment) for segment in segments
        ]
        results = self.openfigi.map(jobs)
        composite = results[0] if composite_job else None
        probes = results[1:] if composite_job else results
        return self._listing_from(composite, probes, segments, mic, run)

    def _listing_from(
        self,
        composite: MappingResult | None,
        probes: list[MappingResult],
        segments: tuple[str, ...],
        mic: str,
        run: _Run,
    ) -> Listing | None:
        operating = operating_mic(mic)
        self._record_mapping([r for r in [composite, *probes] if r is not None], run)
        hits = [(seg, r.figis[0]) for seg, r in zip(segments, probes, strict=True) if r.figis]
        rows: tuple[Figi, ...] = composite.figis if composite is not None else ()
        if len(rows) > 1:
            run.reasons.append(f"OpenFIGI has {len(rows)} composite FIGIs for one listing")
        row = rows[0] if rows else (hits[0][1] if hits else None)
        if row is None:
            run.notes.append(f"OpenFIGI found no listing on {mic}")
            return None
        segment: str | None = None
        if len(hits) == 1:
            segment = hits[0][0]
        elif len(hits) > 1:
            run.reasons.append(f"OpenFIGI matched {len(hits)} segments of {operating}")
        return Listing(
            ticker=row.ticker,
            exchange_mic=operating,
            segment_mic=segment,
            figi=row.composite_figi or row.figi,
            share_class_figi=row.share_class_figi,
            instrument_type=_instrument_type(row),
            security_type2=row.security_type2,
            currency=MIC_CURRENCY.get(operating),
            figi_name=row.name or None,
        )

    def _record_mapping(self, results: list[MappingResult], run: _Run) -> None:
        url = self.openfigi.mapping_url
        for result in results:
            job = result.job.body()
            if result.error:
                run.fact("openfigi", url, f"{job}: error {result.error!r}")
            elif not result.figis:
                run.fact("openfigi", url, f"{job}: {result.warning or 'no match'}")
            else:
                figis = ", ".join(f"{f.figi} ({f.exch_code})" for f in result.figis)
                run.fact("openfigi", url, f"{job}: {figis}")

    def _lei_for(
        self, entity: SecEntity, mention: Mention, run: _Run
    ) -> tuple[LeiRecord | None, list[LeiRecord]]:
        """The GLEIF record for an SEC entity, by exact legal name, then full text (whose
        hits are only candidates: it returns parents with their subsidiaries)."""
        names = _sec_names(entity, None)
        records = [r for r in self.gleif.by_legal_name(entity.name) if _names_agree(names, r.names)]
        if len(records) == 1:
            return records[0], []
        if len(records) > 1:
            run.reasons.append(f"GLEIF has {len(records)} records named {entity.name!r}")
            return None, records
        found = self.gleif.fulltext(entity.name)
        if found:
            run.reasons.append(f"GLEIF has no record named {entity.name!r}; full-text hits only")
        else:
            run.notes.append(f"GLEIF has no LEI for {entity.name!r}")
        return None, found

    def _cik_for(
        self, record: LeiRecord, mention: Mention, run: _Run, ignored: frozenset[str]
    ) -> tuple[SecEntity, ProposalTier] | None:
        """The SEC entity for a GLEIF record, by name (legal, other, transliterated)."""
        ciks: list[str] = []
        for name in record.names:
            for row in self.sec.by_name(name):
                if row.cik not in ignored and row.cik not in ciks:
                    ciks.append(row.cik)
        if not ciks:
            return None
        if len(ciks) > 1:
            run.reasons.append(f"SEC has {len(ciks)} CIKs named like LEI {record.lei}")
            return None
        entity = self._submissions(ciks[0], run)
        if entity is None or entity.adr_shell:
            if entity is not None:
                run.notes.append(f"CIK {entity.cik} is an unsponsored-ADR shell: not linked")
            return None
        agrees = _jurisdiction_agrees(
            entity.state_of_incorporation, mention.country, record.jurisdiction
        )
        return entity, "corroborated" if agrees else "candidate"

    def _lei_proposal(
        self,
        record: LeiRecord,
        run: _Run,
        *,
        linked_by_name: bool,
        sec_entity: SecEntity | None,
        mention: Mention,
        name_ok: bool,
    ) -> Proposal:
        reasons: list[str] = []
        tier: ProposalTier = "exact"
        owner = False
        if sec_entity is not None:
            # A CIK↔LEI link: no source asserts it, so only the owner commits it.
            owner = True
            agrees = _jurisdiction_agrees(
                sec_entity.state_of_incorporation, mention.country, record.jurisdiction
            )
            if agrees is None:
                reasons.append("the jurisdictions can't be compared")
            elif not agrees:
                reasons.append(
                    f"SEC incorporation {sec_entity.state_of_incorporation} vs GLEIF"
                    f" {record.jurisdiction}"
                )
            tier = "corroborated" if agrees else "candidate"
        if linked_by_name and sec_entity is None:
            tier = "candidate"
        status = record.registration_status or ""
        if status in _REVIEW_LEI_STATUSES or record.successor_leis:
            reasons.append(f"LEI {record.lei} is {status or 'superseded'}")
            tier = "candidate"
        if not name_ok:
            tier = "candidate"
        if tier == "candidate":
            owner = True
        run.fact(
            "gleif",
            record.url,
            f"{record.legal_name!r} ({record.jurisdiction}, {status or 'status unknown'})",
        )
        return Proposal(
            kind="lei",
            value=record.lei,
            tier=tier,
            source="gleif",
            url=record.url,
            observed_at=run.now,
            owner_confirmation=owner,
            reasons=reasons,
            details=_lei_details(record),
        )

    def _listing_proposal(
        self, listing: Listing, names: list[str], issuer_tier: ProposalTier, run: _Run
    ) -> Proposal:
        reasons: list[str] = []
        tier: ProposalTier = "exact"
        if listing.instrument_type == "adr":
            reasons.append("an ADR: confirm the underlying issuer and the ratio")
            tier = "candidate"
        elif listing.figi_name and not _names_agree(names, [listing.figi_name]):
            reasons.append(f"OpenFIGI names it {listing.figi_name!r}")
            tier = "candidate"
        if listing.exchange_mic in SEGMENTS and listing.segment_mic is None:
            reasons.append(f"no single {listing.exchange_mic} segment matched")
            tier = "candidate"
        if listing.currency is None:
            reasons.append(f"no currency known for {listing.exchange_mic}")
            tier = "candidate"
        tier = _worst(tier, issuer_tier)
        run.reasons.extend(r for r in reasons if r not in run.reasons)
        return Proposal(
            kind="listing",
            value=f"{listing.ticker}@{listing.exchange_mic}",
            tier=tier,
            source="openfigi",
            url=self.openfigi.mapping_url,
            observed_at=run.now,
            owner_confirmation=tier == "candidate",
            reasons=reasons,
            details=listing.model_dump(),
        )

    def _by_name(self, mention: Mention, run: _Run, ignored: frozenset[str]) -> Resolution:
        """Name only: candidates from SEC's ticker file and GLEIF, never committed."""
        assert mention.name is not None
        run.reasons.append("name only")
        candidates: list[Entity] = []
        proposals: list[Proposal] = []
        seen: set[str] = set()
        for row in self.sec.by_name(mention.name):
            if row.cik in ignored or row.cik in seen:
                continue
            seen.add(row.cik)
            entity = self._submissions(row.cik, run)
            if entity is None:
                continue
            if entity.adr_shell:
                run.notes.append(f"CIK {entity.cik} is an unsponsored-ADR shell: skipped")
                continue
            candidates.append(self._sec_entity_view(entity))
            proposals.append(
                Proposal(
                    kind="cik",
                    value=entity.cik,
                    tier="candidate",
                    source="sec",
                    url=entity.url,
                    observed_at=run.now,
                    owner_confirmation=True,
                    reasons=["name only"],
                    details={"name": entity.name},
                )
            )
        records = self.gleif.by_legal_name(mention.name)
        if not records:
            records = self.gleif.fulltext(mention.name)
        for record in records:
            if record.lei in seen:
                continue
            seen.add(record.lei)
            run.fact("gleif", record.url, f"name {mention.name!r}: {record.legal_name!r}")
            candidates.append(_lei_entity(record))
            reasons = ["name only"]
            agrees = _jurisdiction_agrees(None, mention.country, record.jurisdiction)
            if agrees is False:
                reasons.append(f"GLEIF jurisdiction {record.jurisdiction}, not {mention.country}")
            proposals.append(
                Proposal(
                    kind="lei",
                    value=record.lei,
                    tier="candidate",
                    source="gleif",
                    url=record.url,
                    observed_at=run.now,
                    owner_confirmation=True,
                    reasons=reasons,
                    details=_lei_details(record),
                )
            )
        return self._finish(mention, run, None, candidates, proposals, review=True)

    # --- results ---

    @staticmethod
    def _sec_entity_view(entity: SecEntity) -> Entity:
        return Entity(
            name=entity.name,
            cik=entity.cik,
            state_of_incorporation=entity.state_of_incorporation,
            aliases=_sec_aliases(entity),
        )

    def _conflict(
        self, mention: Mention, run: _Run, reason: str, chains: list[Entity]
    ) -> Resolution:
        run.reasons.append(reason)
        return Resolution(
            mention=mention,
            tier="conflict",
            entity=None,
            candidates=chains,
            proposals=[],
            review_reasons=run.reasons,
            notes=run.notes,
            evidence=run.evidence,
            dropped=run.dropped,
        )

    def _finish(
        self,
        mention: Mention,
        run: _Run,
        entity: Entity | None,
        candidates: list[Entity],
        proposals: list[Proposal],
        *,
        review: bool = False,
    ) -> Resolution:
        tier: Tier
        if proposals:
            tier = _worst(*(p.tier for p in proposals))
        elif entity is not None:
            tier = "exact"
        elif candidates:
            tier = "candidate"
        else:
            tier = "unresolved"
        if review and tier in ("exact", "corroborated"):
            tier = "candidate"
        return Resolution(
            mention=mention,
            tier=tier,
            entity=entity,
            candidates=candidates,
            proposals=proposals,
            review_reasons=run.reasons,
            notes=run.notes,
            evidence=run.evidence,
            dropped=run.dropped,
        )
