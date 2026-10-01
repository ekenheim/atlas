"""Word-level three-way merge of a file git left conflicted.

Usage: python wordmerge.py <path> [<path> ...]   (run from the repo root, mid-merge)

Each of the three stages (base, ours, theirs) is split into tokens, one per line (a token is
a run of non-space characters or a run of whitespace, newlines kept as their own tokens), the
token files are merged with `git merge-file`, and the result is joined back. Two edits to
different parts of one long line then merge cleanly. Prints how many conflicts remain; a
remaining conflict is written with markers on their own lines.
"""

import pathlib
import re
import subprocess
import sys
import tempfile

TOKEN = re.compile(r"\n|[^\S\n]+|\S+")


def stage(number: int, path: str) -> str:
    raw = subprocess.run(
        ["git", "show", f":{number}:{path}"], check=True, capture_output=True
    ).stdout.decode("utf-8")
    return raw.replace("\r\n", "\n")


def encode(text: str) -> str:
    out = []
    for token in TOKEN.findall(text):
        if token == "\n":
            out.append("\\n")
        else:
            out.append(token.replace("\\", "\\\\").replace(" ", "\\s").replace("\t", "\\t"))
    return "\n".join(out) + "\n"


def decode(encoded: str) -> str:
    out = []
    for line in encoded.split("\n"):
        if line.startswith(("<<<<<<<", "=======", ">>>>>>>", "|||||||")):
            out.append("\n" + line + "\n")
            continue
        if line == "\\n":
            out.append("\n")
            continue
        token, i = [], 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line):
                token.append({"s": " ", "t": "\t", "\\": "\\"}.get(line[i + 1], line[i + 1]))
                i += 2
            else:
                token.append(line[i])
                i += 1
        out.append("".join(token))
    return "".join(out)


def merge(path: str) -> int:
    with tempfile.TemporaryDirectory() as directory:
        files = {}
        for name, number in (("base", 1), ("ours", 2), ("theirs", 3)):
            target = pathlib.Path(directory) / name
            target.write_text(encode(stage(number, path)), encoding="utf-8", newline="\n")
            files[name] = str(target)
        result = subprocess.run(
            ["git", "merge-file", "-p", files["ours"], files["base"], files["theirs"]],
            capture_output=True,
        )
        merged = decode(result.stdout.decode("utf-8"))
    working = pathlib.Path(path)
    crlf = b"\r\n" in working.read_bytes()
    with open(working, "w", encoding="utf-8", newline="") as handle:
        handle.write(merged.replace("\n", "\r\n") if crlf else merged)
    return merged.count("\n<<<<<<<")


if __name__ == "__main__":
    for target in sys.argv[1:]:
        print(target, "conflicts left:", merge(target))
