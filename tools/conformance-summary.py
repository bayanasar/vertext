#!/usr/bin/env python3
"""The summary of docs/CONFORMANCE.md, counted from its own tables.

The summary gives, for CLReq and for MLReq, how many rows carry each status.
It was counted by hand, and every change to a row has had to recount it. This
counts the rows of each standard's tables (a table whose header begins
`| Section | Status |`, between that standard's `## ` heading and the next)
and fails where a number in the summary differs.

Usage
-----
    python3 tools/conformance-summary.py
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCUMENT = ROOT / "docs" / "CONFORMANCE.md"
STATUSES = ["Conforms", "Partial", "Not implemented", "Informative"]


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def counted(lines):
    """Rows per status in each standard's section tables."""
    counts, standard, in_table = {}, None, False
    for line in lines:
        if line.startswith("## "):
            standard = line[3:].strip()
            in_table = False
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        row = cells(line)
        if row[:2] == ["Section", "Status"]:
            in_table = True
            continue
        if not in_table or set(row[0]) <= set("-: "):
            continue
        status = row[1]
        if status not in STATUSES:
            sys.exit(f"{standard}: `{row[0]}` has the status `{status}`, "
                     f"which is none of {STATUSES}")
        tally = counts.setdefault(standard, dict.fromkeys(STATUSES, 0))
        tally[status] += 1
    return counts


def summary(lines):
    """The numbers the summary table states, by standard."""
    stated, header = {}, None
    for line in lines:
        if not line.startswith("|"):
            if header:
                break
            continue
        row = cells(line)
        if row[1:] == STATUSES:
            header = row
            continue
        if header and not set(row[0]) <= set("-: "):
            stated[row[0]] = dict(zip(STATUSES, (int(n) for n in row[1:])))
    return stated


def main():
    lines = DOCUMENT.read_text(encoding="utf-8").splitlines()
    counts, stated = counted(lines), summary(lines)
    fails = []
    if set(stated) != set(counts):
        fails.append(f"the summary names {sorted(stated)}, the tables {sorted(counts)}")
    for standard in sorted(set(stated) & set(counts)):
        for status in STATUSES:
            if stated[standard][status] != counts[standard][status]:
                fails.append(f"{standard} {status}: the summary says "
                             f"{stated[standard][status]}, the tables have "
                             f"{counts[standard][status]}")
    for line in fails:
        print("FAIL: " + line)
    if fails:
        return 1
    print("PASS: the summary of docs/CONFORMANCE.md matches its tables: "
          + "; ".join(f"{s} " + "/".join(str(counts[s][k]) for k in STATUSES)
                      for s in sorted(counts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
