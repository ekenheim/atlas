"""Integration helpers: take one side of the migration-head conflict and re-point a migration.

Usage (repo root, mid-merge):
  python rechain.py head <revision>            resolve test_migrations.py's head conflict to <revision>
  python rechain.py down <revision> <new_down>  set a migration's down_revision (and its "Revises:" line)
"""

import glob
import re
import sys


def read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def head(revision):
    path = "tests/integration/test_migrations.py"
    text = read(path)
    pattern = re.compile(
        r"<<<<<<< [^\r\n]*\r?\n(?P<ours>.*?)=======\r?\n(?P<theirs>.*?)>>>>>>> [^\r\n]*\r?\n", re.S
    )
    matches = list(pattern.finditer(text))
    assert matches, "no conflict in test_migrations.py"
    for match in reversed(matches):
        ours, theirs = match.group("ours"), match.group("theirs")
        if "assert revision ==" in ours and "assert revision ==" in theirs:
            chosen = re.sub(r'assert revision == "\d+"', f'assert revision == "{revision}"', theirs)
        else:
            raise SystemExit(f"a conflict that is not the head assertion:\n{ours}\n---\n{theirs}")
        text = text[: match.start()] + chosen + text[match.end() :]
    write(path, text)
    print("head ->", revision)


def down(revision, new_down):
    (path,) = glob.glob(f"backend/atlas/db/migrations/versions/{revision}_*.py")
    text = read(path)
    text, count = re.subn(r'down_revision = "\d+"', f'down_revision = "{new_down}"', text)
    assert count == 1, path
    text, revises = re.subn(r"(Revises: )\d+", rf"\g<1>{new_down}", text)
    write(path, text)
    print(path, "down_revision ->", new_down, f"(Revises lines changed: {revises})")


if __name__ == "__main__":
    if sys.argv[1] == "head":
        head(sys.argv[2])
    else:
        down(sys.argv[2], sys.argv[3])
