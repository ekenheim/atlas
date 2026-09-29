"""robots.txt, parsed and matched as RFC 9309 (the Robots Exclusion Protocol) specifies.

Python's `urllib.robotparser` is not used: it applies the first matching rule rather than
the most specific one, and treats 401/403 as "disallow all", both unlike RFC 9309.

- **Groups.** One or more `user-agent` lines start a group; its `allow`/`disallow` lines
  follow. Atlas obeys every group naming its product token (`AtlasResearch`, compared
  case-insensitively), merged; else every `*` group, merged; else nothing restricts it.
  Rules before any `user-agent` line, and other keys (`sitemap`, `crawl-delay`), are ignored.
- **Matching.** A rule's path matches a URL's path and query from the start; `*` matches any
  run of characters and a final `$` anchors the end. Both sides are compared with their
  percent-encoding normalized. The longest matching path wins; between an `allow` and a
  `disallow` of the same length, `allow` wins. No match means allowed. `/robots.txt` itself
  is always allowed. An empty `disallow:` is no rule.
- **Fetch status** (the gate maps it): a 2xx body is parsed (at most 500 KiB of it); a 4xx
  means no restrictions; a 5xx, a network error or a timeout means complete disallow.
  An HTML error page served with 200 has no directives, so it restricts nothing.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

# The product token Atlas identifies itself by in robots.txt groups.
ROBOTS_PRODUCT_TOKEN = "AtlasResearch"  # noqa: S105 (not a secret)
MAX_ROBOTS_BYTES = 500 * 1024  # RFC 9309 §2.5: parse at least the first 500 KiB
_SAFE = "!$&'()*+,/:;=?@-._~"  # reserved and unreserved characters kept as they are


@dataclass(frozen=True)
class RobotsRule:
    allow: bool
    path: str  # as written in the file
    line: int  # 1-based line number in the file

    def describe(self) -> str:
        return f"{'Allow' if self.allow else 'Disallow'}: {self.path} (line {self.line})"


@dataclass(frozen=True)
class RobotsVerdict:
    allowed: bool
    rule: RobotsRule | None  # the deciding rule; None when no rule matched
    group: str | None  # the user-agent the obeyed group names ("atlasresearch" or "*")
    reason: str


def _normalize(value: str) -> str:
    return quote(unquote(value), safe=_SAFE + "%")


def _pattern(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    regex = ".*".join(re.escape(_normalize(part)) for part in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""), re.DOTALL)


@dataclass(frozen=True)
class _Group:
    agents: tuple[str, ...]  # lowercased
    rules: tuple[RobotsRule, ...]


class RobotsTxt:
    """One site's robots.txt, ready to answer whether Atlas may fetch a URL there."""

    def __init__(self, groups: tuple[_Group, ...], *, disallow_all: str | None = None) -> None:
        self._groups = groups
        self._disallow_all = disallow_all

    @classmethod
    def parse(cls, body: bytes) -> "RobotsTxt":
        text = body[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")
        groups: list[_Group] = []
        agents: list[str] = []
        rules: list[RobotsRule] = []
        in_rules = False
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:  # a user-agent after rules starts the next group
                    groups.append(_Group(tuple(agents), tuple(rules)))
                    agents, rules, in_rules = [], [], False
                if value:
                    agents.append(value.lower())
            elif key in ("allow", "disallow"):
                if not agents:
                    continue  # a rule outside any group
                in_rules = True
                if value:
                    rules.append(RobotsRule(allow=key == "allow", path=value, line=number))
        if agents:
            groups.append(_Group(tuple(agents), tuple(rules)))
        return cls(tuple(groups))

    @classmethod
    def unrestricted(cls) -> "RobotsTxt":
        """No robots.txt (a 4xx): nothing is restricted."""
        return cls(())

    @classmethod
    def unreachable(cls, why: str) -> "RobotsTxt":
        """robots.txt could not be read (5xx, network error): everything is disallowed."""
        return cls((), disallow_all=why)

    def check(self, url: str, token: str = ROBOTS_PRODUCT_TOKEN) -> RobotsVerdict:
        parts = urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if (parts.path or "/") == "/robots.txt":
            return RobotsVerdict(True, None, None, "/robots.txt is always allowed")
        if self._disallow_all is not None:
            return RobotsVerdict(False, None, None, self._disallow_all)
        wanted = token.lower()
        mine = [g for g in self._groups if wanted in g.agents]
        group = wanted if mine else "*"
        obeyed = mine or [g for g in self._groups if "*" in g.agents]
        if not obeyed:
            return RobotsVerdict(True, None, None, "no group applies to Atlas")
        target = _normalize(target)
        best: RobotsRule | None = None
        for rule in (rule for g in obeyed for rule in g.rules):
            if not _pattern(rule.path).match(target):
                continue
            longer = best is None or len(rule.path) > len(best.path)
            tie_to_allow = best is not None and len(rule.path) == len(best.path) and rule.allow
            if longer or tie_to_allow:
                best = rule
        if best is None:
            return RobotsVerdict(True, None, group, f"no rule of the {group!r} group matches")
        verb = "allows" if best.allow else "disallows"
        return RobotsVerdict(best.allow, best, group, f"{best.describe()} {verb} it")
