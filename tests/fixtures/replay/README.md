# Replay fixtures (hand-written, synthetic)

Three short HTML documents for the replay leakage gate (ticket 22,
`tests/integration/test_replay.py`). They are **not** real disclosures: they were written by
hand for the test, name no real figures, and are imported with `atlas sources import` under
the publication times the test gives them:

- `early-capacity-update.html`: published before the test's cutoff
- `mid-customer-update.html`: published before the cutoff, after the early one
- `future-dated-supply-shock.html`: the **future-dated** fixture, published after the cutoff;
  a replay must accept it 0 times (not retained, recalled or cited). Its marker phrase,
  "indium phosphide wafer shortage of the future quarter", appears in no other fixture.
