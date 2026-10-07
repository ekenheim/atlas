# 39: `owns` from an investment or a warrant, with the direction reversed

**Status:** done (2026-10-07, integrate/fixes-1)
**Hurt:** investigations 1, 2 and 3, verdict runs on 0.4.6.

"NVIDIA's $2 billion equity investment in Coherent" becomes "Coherent owns NVIDIA" (`5cd6f7b1`, `093d6525`); a warrant Applied Optoelectronics issued to an Amazon subsidiary becomes "Applied Optoelectronics owns Amazon.com, Inc." (`79496d5c`).

**Acceptance:** the party check rejects an `owns` whose subject is the company invested in or the issuer of the security; the three quotes are regression cases.
