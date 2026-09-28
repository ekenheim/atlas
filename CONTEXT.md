# Atlas Research

An evidence-driven investment research platform: it discovers industry bottlenecks, maps exposed companies through source-backed evidence, and freezes falsifiable hypotheses for later evaluation. It researches; it never trades.

## Language

### Sources and evidence

**Source Document**:
The stable identity of a piece of source material (a URL, or an SEC accession), independent of any particular copy.
_Avoid_: Document (unqualified), page, filing (when the identity is meant)

**Source Version**:
One immutable, hash-identified copy of a Source Document as fetched at a point in time. Any change to the content is a new Source Version, never an edit.
_Avoid_: Revision, snapshot (reserved for Research Snapshot)

**Claim**:
A statement proposed by an agent or extractor that has not yet been validated against a Source Version. Untrusted by default.
_Avoid_: Fact, finding

**Assertion**:
A ledger record binding a statement to one Source Version and an exact quote span, carrying an epistemic type and a review state. A Claim becomes an Assertion only once its span is confirmed in the archived text.
_Avoid_: Claim (once validated), fact

**Evidence**:
Assertions and the Source Versions behind them, when used to support or refute something. Only primary material counts as Evidence.
_Avoid_: Memory, citation (as a synonym)

**Evidence Family**:
A set of Source Versions that are not independent of each other, such as one announcement syndicated across many sites. The family counts as a single witness.
_Avoid_: Duplicate group, cluster

**Memory**:
Anything derived and held by Hindsight: extracted facts, observations, mental models, knowledge pages. Memory can lead to Evidence but is never Evidence itself, and never counts as an independent witness.
_Avoid_: Evidence, knowledge (unqualified)

### Research objects

**Bottleneck**:
An input, process or capacity that cannot meet demand within the relevant timeframe because no qualified second source or substitute exists, giving its holder pricing power. It is a claim that needs Evidence, not a conclusion drawn from demand growth alone.
_Avoid_: Shortage, chokepoint, constraint (as a synonym)

**Candidate**:
A (company, theme) pair under investigation, with its own lifecycle from lead to rejected or closed. Kept even when rejected, so evaluation isn't winner-only. A Candidate may produce zero or more Hypotheses.
_Avoid_: Idea, pick, opportunity

**Hypothesis**:
A versioned, falsifiable research object: statement, mechanism, predictions, catalysts, falsifiers and alternative explanations. A published version is immutable; a correction is a new version.
_Avoid_: Thesis (as a standalone noun), idea, call

**Thesis Statement**:
The one-sentence claim at the head of a Hypothesis. It is a field of a Hypothesis, not a separate object.
_Avoid_: Thesis

**Relationship**:
A reviewed, typed, directed edge between companies (and optionally a product or theme), drawn from a fixed predicate whitelist and backed by Assertions.
_Avoid_: Link, connection, edge (outside the UI)

**Research Snapshot**:
An immutable, dated record of exactly what was considered and concluded at a decision time, including the Memory text as it was returned. It is the only exact mechanism for reproducing past beliefs.
_Avoid_: Backup, export, replay

**Replay Bank**:
An isolated Hindsight bank populated only with material available before a cutoff, used to evaluate the pipeline. It does not reproduce a past run.
_Avoid_: Historical bank, backtest
