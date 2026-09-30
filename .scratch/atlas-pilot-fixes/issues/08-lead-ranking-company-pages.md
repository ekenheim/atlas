# 08: Lead ranking keeps the companies' own pages over industry articles

**What to build:** In pilot investigation 1's re-run (0.2.3), the 10 leads kept (of 100) were all the seed companies' own pages: investor relations, homepage, LinkedIn, "About us", "Lasers | Coherent". They are on-topic but tell a researcher nothing; the Scout's queries were written for industry articles about EML capacity, InP substrates and MOCVD tools, and those (if found) were among the 90 rejected. `configs/discovery/lead-ranking.yaml` rewards a universe company name in the title (`names Coherent`) as much as query terms. Change the ranking so query- and purpose-specific terms outweigh company names, demote the seed companies' own domains and social or profile hosts (LinkedIn, Crunchbase, Wikipedia is already demoted), and keep the score and reasons visible. Tune against the re-run's recorded results (discovery `e9565f0d-9e28-41b2-bb92-f9dbe0cdd4c5`) as a fixture.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] A fixture built from the re-run's 100 results; the unit test shows industry articles ranking above the companies' own pages for the same query.
- [ ] The kept leads of an investigation record why they were kept, as now.
