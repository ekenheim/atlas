"""The Entity Resolver's tiers (exact, corroborated, candidate, conflict) over the identity
fixtures, through `EntityResolver.resolve`.

Cases are the identity research's pipeline cases (docs/research/identity-apis.md §6, branch
`research/identity-apis`); expected identifiers are the research's recorded values.
"""

from datetime import UTC, date, datetime

from atlas.identity import EntityResolver, Mention, Resolution
from atlas.identity.gleif import GleifClient
from atlas.identity.normalize import normalize_name
from atlas.identity.openfigi import OpenFigiClient
from atlas.identity.sec import SecIdentityClient
from atlas.sources.sec_http import TokenBucket
from tests.fakes.identity import FakeIdentitySources

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
LUMENTUM_CIK, LUMENTUM_LEI = "0001633978", "549300JLWRRC38DWEF52"
COHERENT_CIK, COHERENT_LEI = "0000820318", "549300O5C25A0MMHHU33"
TSMC_CIK, TSMC_LEI = "0001046179", "549300KB6NK5SBD14S87"


def no_sleep(_: float) -> None:
    pass


def resolver(fake: FakeIdentitySources) -> EntityResolver:
    def limiter() -> TokenBucket:
        return TokenBucket(1000)

    return EntityResolver(
        SecIdentityClient(
            "Atlas Research ops@example.com",
            transport=fake.transport,
            limiter=limiter(),
            sleep=no_sleep,
        ),
        GleifClient(transport=fake.transport, limiter=limiter(), sleep=no_sleep),
        OpenFigiClient(transport=fake.transport, limiter=limiter(), sleep=no_sleep),
        clock=lambda: NOW,
    )


def resolve(mention: Mention, **kwargs: frozenset[str]) -> tuple[Resolution, FakeIdentitySources]:
    fake = FakeIdentitySources()
    return resolver(fake).resolve(mention, **kwargs), fake


def proposals(resolution: Resolution) -> dict[str, tuple[str, str, bool]]:
    """kind:value → (tier, source, needs the owner)."""
    return {
        f"{p.kind}:{p.value}": (p.tier, p.source, p.owner_confirmation)
        for p in resolution.proposals
    }


def test_lumentum_by_cik() -> None:
    resolution, fake = resolve(Mention(cik="1633978"))

    assert proposals(resolution) == {
        # The CIK came in and SEC agrees: exact, committed automatically.
        f"cik:{LUMENTUM_CIK}": ("exact", "sec", False),
        # No source links a CIK to an LEI: name + jurisdiction (DE ↔ US-DE) corroborates
        # it, and only the owner commits it.
        f"lei:{LUMENTUM_LEI}": ("corroborated", "gleif", True),
        "listing:LITE@XNAS": ("exact", "openfigi", False),
    }
    assert resolution.tier == "corroborated"
    entity = resolution.entity
    assert entity is not None
    assert (entity.name, entity.cik, entity.lei, entity.jurisdiction) == (
        "Lumentum Holdings Inc.",
        LUMENTUM_CIK,
        LUMENTUM_LEI,
        "US-DE",
    )
    [listing] = entity.listings
    # The operating MIC is stored; OpenFIGI matched the Global Select segment.
    assert (listing.exchange_mic, listing.segment_mic) == ("XNAS", "XNGS")
    # The composite (country-level) FIGI, not the venue FIGI BBG0073F9SD2.
    assert (listing.figi, listing.share_class_figi) == ("BBG0073F9RT7", "BBG0073F9RS8")
    assert (listing.instrument_type, listing.currency) == ("common", "USD")
    # OpenFIGI was never asked for XNAS as a micCode (it doesn't match there).
    jobs = [job for batch in fake.openfigi_batches for job in batch]
    assert {"idType": "TICKER", "idValue": "LITE", "micCode": "XNAS"} not in jobs
    assert {"idType": "TICKER", "idValue": "LITE", "micCode": "XNGS"} in jobs
    assert resolution.review_reasons == []
    assert all(fact.observed_at == NOW for fact in resolution.evidence)


def test_coherent_by_ticker_on_its_venue_keeps_its_lapsed_lei() -> None:
    resolution, _ = resolve(Mention(ticker="COHR", mic="XNYS"))

    assert proposals(resolution) == {
        f"cik:{COHERENT_CIK}": ("exact", "sec", False),
        # LAPSED means the renewal is overdue; the LEI still identifies Coherent.
        f"lei:{COHERENT_LEI}": ("corroborated", "gleif", True),
        "listing:COHR@XNYS": ("exact", "openfigi", False),
    }
    entity = resolution.entity
    assert entity is not None
    assert entity.lei_status == "LAPSED"
    assert resolution.review_reasons == []
    [listing] = entity.listings
    assert (listing.figi, listing.segment_mic) == ("BBG000BLW102", "XNYS")
    # SEC's former name, with its dates, and GLEIF's other name become aliases.
    former = [(a.name, a.kind, a.valid_from, a.valid_to, a.source) for a in entity.aliases]
    assert (
        "II-VI INC",
        "former",
        date(1995, 10, 4),
        date(2022, 9, 1),
        "sec",
    ) in former
    assert ("II-VI Incorporated", "other", None, None, "gleif") in former


def test_an_lei_alone_links_its_cik_by_name_and_jurisdiction() -> None:
    resolution, _ = resolve(Mention(lei=COHERENT_LEI))

    table = proposals(resolution)
    # The LEI came in: exact. The CIK is joined on name ("Coherent Corp." = "COHERENT CORP.")
    # and jurisdiction (US-PA ↔ PA): corroborated, and a CIK↔LEI link for the owner.
    assert table[f"lei:{COHERENT_LEI}"] == ("exact", "gleif", False)
    assert table[f"cik:{COHERENT_CIK}"] == ("corroborated", "sec", True)
    assert resolution.tier == "corroborated"


def test_an_adr_goes_to_review_with_the_foreign_issuer() -> None:
    resolution, _ = resolve(Mention(ticker="TSM", mic="XNYS"))

    assert resolution.tier == "candidate"
    entity = resolution.entity
    assert entity is not None
    # The ADR ticker is filed under TSMC's own CIK: the issuer is TSMC.
    assert entity.cik == TSMC_CIK
    [listing] = entity.listings
    assert (listing.instrument_type, listing.figi, listing.share_class_figi) == (
        "adr",
        "BBG000BD8ZK0",
        "BBG001S5WWW4",
    )
    tier, _, owner = proposals(resolution)["listing:TSM@XNYS"]
    assert (tier, owner) == ("candidate", True)
    assert any("ADR" in reason for reason in resolution.review_reasons)


def test_an_adr_isin_resolves_to_the_underlying_issuer_for_review() -> None:
    resolution, _ = resolve(Mention(isin="US8740391003"))

    assert resolution.tier == "candidate"
    entity = resolution.entity
    assert entity is not None
    assert (entity.lei, entity.cik) == (TSMC_LEI, TSMC_CIK)
    assert any("depositary receipt" in reason for reason in resolution.review_reasons)


def test_a_name_alone_gives_candidates_and_never_commits() -> None:
    resolution, fake = resolve(Mention(name="Lumentum"))

    assert resolution.tier == "candidate"
    assert resolution.entity is None
    # Full text returns the holding company and two subsidiaries: a name can't choose.
    assert sorted(c.lei or "" for c in resolution.candidates) == sorted(
        [LUMENTUM_LEI, "5493000SYNTHETIC0133", "2138008B3OEMZ9XKZP41"]
    )
    assert resolution.proposals
    assert not any(p.auto_commit for p in resolution.proposals)
    assert "name only" in resolution.review_reasons
    # GLEIF's fuzzy completions are never used.
    assert not any("fuzzycompletions" in path for path in fake.paths())


def test_a_conflicting_isin_and_cik_propose_nothing() -> None:
    # Lumentum's ISIN with Coherent's CIK.
    resolution, _ = resolve(Mention(isin="US55024U1097", cik=COHERENT_CIK))

    assert resolution.tier == "conflict"
    assert resolution.proposals == []
    assert resolution.entity is None
    # Both chains of evidence are shown.
    assert {c.cik for c in resolution.candidates} >= {COHERENT_CIK}
    assert {c.lei for c in resolution.candidates} >= {LUMENTUM_LEI}
    assert any("CIK 0000820318" in r and LUMENTUM_LEI in r for r in resolution.review_reasons)


def test_a_ticker_on_another_ciks_company_is_a_conflict() -> None:
    resolution, _ = resolve(Mention(ticker="LITE", mic="XNAS", cik=COHERENT_CIK))

    assert resolution.tier == "conflict"
    assert resolution.proposals == []


def test_a_ticker_without_a_venue_needs_review() -> None:
    resolution, _ = resolve(Mention(ticker="LITE"))

    assert resolution.tier == "candidate"
    entity = resolution.entity
    assert entity is not None
    assert entity.cik == LUMENTUM_CIK
    assert "ticker LITE came without a venue" in resolution.review_reasons
    assert not any(p.auto_commit for p in resolution.proposals if p.kind == "cik")


def test_invalid_identifiers_are_dropped_not_repaired() -> None:
    resolution, fake = resolve(Mention(isin="US0000000000", lei="549300O5C25A0MMHHU34"))

    assert resolution.tier == "unresolved"
    assert len(resolution.dropped) == 2
    assert fake.calls == []


def test_an_ignored_cik_is_never_used() -> None:
    resolution, _ = resolve(
        Mention(name="Soitec SA", country="FR"), ignored_ciks=frozenset({"0001445214"})
    )

    assert "cik:0001445214" not in proposals(resolution)
    # GLEIF's SOITEC (FR) is a name-only candidate for the owner.
    assert proposals(resolution) == {"lei:969500ZR92SQCU9TST26": ("candidate", "gleif", True)}


def test_an_unsponsored_adr_shell_found_by_name_is_skipped() -> None:
    resolution, _ = resolve(Mention(name="Soitec SA"))

    assert "cik:0001445214" not in proposals(resolution)
    assert any("unsponsored-ADR shell" in note for note in resolution.notes)


def test_names_are_equal_only_after_normalisation() -> None:
    assert normalize_name("II-VI Incorporated") == normalize_name("II-VI INC")
    assert normalize_name("Coherent Corp.") == normalize_name("COHERENT CORP")
    assert normalize_name("STMicroelectronics N.V.") == normalize_name("STMICROELECTRONICS NV")
    assert normalize_name("Taiwan Semiconductor Manufacturing Company Limited") == normalize_name(
        "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"
    )
    # HOLDINGS is not a legal form: a registrant isn't its operating subsidiary.
    assert normalize_name("MACOM Technology Solutions Holdings, Inc.") != normalize_name(
        "MACOM Technology Solutions Inc."
    )
