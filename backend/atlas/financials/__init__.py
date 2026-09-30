"""As-of financials from XBRL companyfacts (spec Phase 5, "XBRL normalizer"; ticket 18).

`xbrl` parses companyfacts and holds the as-of rules (availability, linkage, suspect flags,
selection), `metrics` the canonical metrics and derived quarters, `service` stores and loads
`financial_observation` rows, `reads` builds the API views.
"""

from atlas.financials.metrics import (
    CurrencyMismatch,
    MetricCatalog,
    MetricValue,
    derive_difference,
    load_metric_catalog,
    metric_values,
)
from atlas.financials.reads import (
    FinancialFigure,
    FinancialFigures,
    FinancialObservation,
    FinancialObservationHistory,
    financial_figures,
    observation_history,
    selected_observations,
)
from atlas.financials.service import (
    NORMALIZER_VERSION,
    LatestCompanyfacts,
    NormalizationFailure,
    NormalizationSummary,
    is_normalized,
    latest_companyfacts,
    normalize_source_version,
    record_normalization_failure,
)
from atlas.financials.xbrl import (
    PERIODIC_FORMS,
    CompanyFact,
    CompanyFacts,
    Observation,
    PeriodKey,
    fact_availability,
    normalize,
    parse_companyfacts,
    select_as_of,
)

__all__ = [
    "NORMALIZER_VERSION",
    "PERIODIC_FORMS",
    "CompanyFact",
    "CompanyFacts",
    "CurrencyMismatch",
    "FinancialFigure",
    "FinancialFigures",
    "FinancialObservation",
    "FinancialObservationHistory",
    "LatestCompanyfacts",
    "MetricCatalog",
    "MetricValue",
    "NormalizationFailure",
    "NormalizationSummary",
    "Observation",
    "PeriodKey",
    "derive_difference",
    "fact_availability",
    "financial_figures",
    "is_normalized",
    "latest_companyfacts",
    "load_metric_catalog",
    "metric_values",
    "normalize",
    "normalize_source_version",
    "observation_history",
    "parse_companyfacts",
    "record_normalization_failure",
    "select_as_of",
    "selected_observations",
]
