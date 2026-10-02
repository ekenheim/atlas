# 18: News in Memory, as leads

**What to build:** Memory knows what the news reports about a company, kept apart from what companies and filings state. An investigation uses it the way a researcher uses news: to know where to look and what to ask, never as proof. The research card lists what the news reports on the question as unverified leads, with their publisher and date, and a company known only from news (Innolight today) appears on the card as pointed at but without a primary source.

Spec: `.scratch/atlas-memory-quality/spec.md` (Memory stays an index). Product spec §4.1: Tier C is a lead; it cannot establish a contract, a shortage or an exposure. The Serenity alignment (`docs/research/serenity-skills-alignment.md` on branch `research/serenity-skills-alignment`, D3 and M15): news and social posts are leads only. Depends on ticket 17's news Source Versions and on the retain profile of tickets 04 and 06.

- **Retained apart.** A news Source Version is retained whole (no triage: stories are short) with the tags `tier:c` and `doctype:news` beside its company and theme tags, the context ticket 04 builds ("News story by <publisher>, published <date>, about <company>; a third party is reporting, not the company"), the named universe companies as entities, and observation scopes of its own (`tier:c` with the company, `tier:c` with the theme), so no observation mixes news with a company's own statements.
- **Recall says which is which.** The scoped recall excludes `tier:c` unless asked (a request field; default off), so every existing use is unchanged. A recalled news memory carries its tier in the answer.
- **Lead pointers.** After the Scout's recalls, one more recall per query with news included yields **lead pointers** (reading pointers of kind `news`): they join the ranking of pointed companies with a low weight (a setting), are never offered to passage selection, and are stored with their story's publisher and date.
- **On the card.** `news_leads`: per company, the stories the lead pointers name (title, publisher, date, link to the Source Version), at most a bound, code's and not the Editor's. `not_read` gains the reason `no_primary_source` for a pointed company with no readable primary document. The Editor is sent the news leads' titles as low-trust retrieved data and may raise open questions from them; a finding may not cite one (code rejects it as it rejects an unknown Claim).
- **The entity hop** (ticket 09) may start from a company named in a news lead, bounded like the rest: that is how a story about Innolight and a customer leads to the customer's filings.
- **Still never:** an Assertion on a news span, a Claim from a story, a contradiction from a story (the Skeptic's witnesses stay Tier A), a mental model reading `tier:c` (the models' scope excludes it).
- Whether a news story may ever support a `third_party_report` Claim that goes to the owner's queue is left open on the pilot-review map; it is not built here.
- `CONTEXT.md` gains **News lead**; `docs/decisions.md`: "News in Memory, as leads".

Migration revision `0069` (down: main's head).

**Blocked by:** 04, 06, 07, 17

**Status:** ready-for-agent

- [ ] Integration test at the worker seam: a news Source Version is retained with `tier:c`, `doctype:news`, its own scopes, the third-party context and its entities; a filing's retain is unchanged.
- [ ] A scoped recall without the field returns no news memory; with it, news memories come back marked Tier C; reflect and the mental models never see them.
- [ ] Integration test at the investigation seam: a company with only news is ranked from lead pointers, gets no Investigator, and is on the card under `not_read` with `no_primary_source`; the card's `news_leads` lists its stories; a finding citing a news lead is dropped as unsupported.
- [ ] No passage of a news Source Version is ever selected (the selection test of ticket 17 extended).
- [ ] The investigation page shows news leads apart from Evidence (frontend unit test of the pure part); API client regenerated.
- [ ] Glossary and decision entries; `AGENTS.md` line.
