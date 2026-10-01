"""The Skeptic's deterministic table-row check (memory-directed reading, ticket 03): a quote
that is a table row with no words is accepted only as bear context, and only with its figure's
name and period (atlas.investigations.skeptic, step 5). The rows are pilot investigation 1's
(`.scratch/atlas-pilot-fixes/issues/16-skeptic-context-recorded-as-contradiction.md`) and the
recorded Coherent and Lumentum 10-Qs' (whose parsed text separates cells by tabs)."""

import pytest

from atlas.investigations.skeptic import is_table_row


@pytest.mark.parametrize(
    "quote",
    [
        "Inventories 2,126,823 1,437,636",
        "Inventories\t2,126,823\t1,437,636",
        "Property, plant & equipment, net 2,420,081 1,877,507",
        "Diluted 96.2 69.3 87.4 68.8",
        "Total Coherent Corp. Shareholders' Equity\t10,676,983\t5,644,514",
        "Cash and cash equivalents\t$\t1,592,730\t$\t909,200",
        "Short-term investments\t825,000\t—",
        "Gain on sale of facility\t—\t(34.9)\t—\t(34.9)",
        "Net income (loss)\t$\t226.6\t$\t(187.4)",
        "2,126,823 1,437,636",
        # A row whose label is a sentence fragment is still a label and its figures.
        "Treasury stock, at cost; 16,794,638 shares at March 31, 2026 and 16,294,119 shares at"
        " June 30, 2025\n(419,645)\t(368,065)",
    ],
)
def test_a_label_followed_only_by_figures_is_a_table_row(quote: str) -> None:
    assert is_table_row(quote)


@pytest.mark.parametrize(
    "quote",
    [
        "We had two customers who each contributed more than 10% of revenue during fiscal 2026.",
        "issued - 212,340,736 shares at March 31, 2026; 171,849,325 shares at June 30, 2025",
        "for certain components we have sole or limited source supply arrangements",
        "Inventories increased to $2,126.8 million from $1,437.6 million",
        "As of April 30, 2026, the Registrant had 77.8 million shares of common stock outstanding.",
        "the agreement no longer commits NVIDIA to purchase from Coherent after December 31, 2027",
        "Inventories 2,126,823",  # a label and one figure
        "March 31, 2026",
        "",
    ],
)
def test_a_sentence_or_a_single_figure_is_not_a_table_row(quote: str) -> None:
    assert not is_table_row(quote)
