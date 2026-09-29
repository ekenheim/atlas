"""Deterministic normalisation and validation of names and identifiers (no network).

An invalid identifier is dropped and reported, never repaired by guessing
(docs/research/identity-apis.md, pipeline step 1).
"""

import re
import unicodedata

# Legal-form tokens dropped from the END of a name before comparing it (the research's fixed
# list, plus INCORPORATED and COMPANY so that "II-VI Incorporated" = "II-VI INC" and TSMC's
# "... Company Limited" = SEC's "... CO LTD"). HOLDINGS is deliberately NOT a legal form:
# dropping it would equate a registrant with its operating subsidiary ("MACOM Technology
# Solutions Holdings, Inc." vs "MACOM Technology Solutions Inc.", seed-list finding 7).
LEGAL_FORMS = frozenset(
    {
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "LTD",
        "LIMITED",
        "PLC",
        "AG",
        "NV",
        "SA",
        "CO",
        "COMPANY",
    }
)
_WORD = re.compile(r"[^\W_]+")


def normalize_name(name: str) -> str:
    """Upper-case, drop dots and apostrophes (N.V. → NV), split on other punctuation, then drop
    trailing legal-form tokens. Names are equal only if these are equal: never a similarity."""
    folded = unicodedata.normalize("NFKC", name).upper().replace(".", "").replace("'", "")
    tokens = _WORD.findall(folded)
    while len(tokens) > 1 and tokens[-1] in LEGAL_FORMS:
        tokens.pop()
    return " ".join(tokens)


def normalize_cik(value: str) -> str | None:
    """Zero-padded to 10 digits, or None when it isn't 1-10 digits."""
    digits = value.strip()
    if not re.fullmatch(r"[0-9]{1,10}", digits) or int(digits) == 0:
        return None
    return digits.zfill(10)


def _alphanumeric_digits(value: str) -> str:
    return "".join(str(int(char, 36)) for char in value)


def valid_isin(value: str) -> bool:
    """ISO 6166: two letters, nine alphanumerics and a Luhn check digit over the digit string."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
        return False
    digits = _alphanumeric_digits(value)
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def valid_lei(value: str) -> bool:
    """ISO 17442: 18 alphanumerics and two check digits, mod 97 = 1 (ISO 7064 MOD 97-10)."""
    if not re.fullmatch(r"[A-Z0-9]{18}[0-9]{2}", value):
        return False
    return int(_alphanumeric_digits(value)) % 97 == 1


def canonical_ticker(value: str) -> str:
    """One form for class suffixes: SEC's `-` (OpenFIGI writes `/`, many feeds `.`)."""
    return re.sub(r"[/.]", "-", value.strip().upper())


def openfigi_ticker(ticker: str) -> str:
    return ticker.replace("-", "/")


# --- venues ---

# ISO 10383 segment MICs by operating MIC, where OpenFIGI's `micCode` needs the segment: it
# matches LITE on XNGS (Nasdaq Global Select), not on the operating MIC XNAS.
SEGMENTS: dict[str, tuple[str, ...]] = {
    "XNAS": ("XNGS", "XNMS", "XNCM"),  # Global Select, Global Market, Capital Market
    "XLON": ("XLON", "AIMX"),  # Main Market, AIM
}
OPERATING_MIC = {segment: operating for operating, s in SEGMENTS.items() for segment in s}

# Bloomberg exchange codes of US venue FIGIs → segment MIC.
BLOOMBERG_VENUE_MIC = {
    "UW": "XNGS",
    "UQ": "XNMS",
    "UR": "XNCM",
    "UN": "XNYS",
    "UA": "XASE",
    "UP": "ARCX",
}
# Operating MICs whose listings OpenFIGI groups under the country composite `US`.
US_MICS = frozenset({"XNAS", "XNYS", "XASE", "ARCX", "BATS"})

# Trading currency by operating MIC (OpenFIGI returns no currency). London quotes in pence
# (GBX) but reports in GBP; GBP is stored.
MIC_CURRENCY = {
    "XNAS": "USD",
    "XNYS": "USD",
    "XASE": "USD",
    "ARCX": "USD",
    "BATS": "USD",
    "XPAR": "EUR",
    "XMIL": "EUR",
    "XAMS": "EUR",
    "XETR": "EUR",
    "XLON": "GBP",
    "XHKG": "HKD",
    "XSHE": "CNY",
    "XSHG": "CNY",
    "XTAI": "TWD",
    "XTKS": "JPY",
}

# SEC's `exchange` is a label, not a MIC; OTC, CBOE and null have no single venue.
SEC_EXCHANGE_MIC = {"Nasdaq": "XNAS", "NYSE": "XNYS"}


def operating_mic(mic: str) -> str:
    return OPERATING_MIC.get(mic, mic)


def segment_mics(mic: str) -> tuple[str, ...]:
    """The segment MICs to ask OpenFIGI for a listing on `mic` (operating or segment)."""
    return SEGMENTS.get(mic, (mic,))


# US state codes as SEC `stateOfIncorporation` writes them (GLEIF writes `US-DE`).
US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH"
    " NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split()
)
