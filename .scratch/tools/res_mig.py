"""Resolve tests/integration/test_migrations.py mid-merge: python res_mig.py <head revision>

The head assertion takes <head revision>. Any other conflict is two branches appending their
own migration tests: from the first such conflict to the end of the file, the result is our
version of that region followed by theirs.
"""

import re
import sys

PATH = "tests/integration/test_migrations.py"
CONFLICT = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)

raw = open(PATH, encoding="utf-8", newline="").read()
crlf = "\r\n" in raw
text = raw.replace("\r\n", "\n")
head = sys.argv[1]

first = CONFLICT.search(text)
if first and "assert revision ==" in first.group(1) and "assert revision ==" in first.group(2):
    text = text[: first.start()] + f'    assert revision == "{head}"\n' + text[first.end() :]
else:
    text, count = re.subn(r'assert revision == "\d+"', f'assert revision == "{head}"', text, count=1)
    assert count == 1

rest = CONFLICT.search(text)
if rest:
    before, region = text[: rest.start()], text[rest.start() :]
    ours = CONFLICT.sub(lambda m: m.group(1), region)
    theirs = CONFLICT.sub(lambda m: m.group(2), region)
    text = before + ours.rstrip("\n") + "\n\n\n" + theirs.rstrip("\n") + "\n"

assert "<<<<<<<" not in text and ">>>>>>>" not in text
open(PATH, "w", encoding="utf-8", newline="").write(text.replace("\n", "\r\n") if crlf else text)
print("test_migrations.py resolved; head", head)
