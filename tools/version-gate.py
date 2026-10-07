#!/usr/bin/env python3
"""The declared version is one string, and honest about where it was built.

Three checks from tools/versions.py:

- every declaration of the version (tools/versions.py lists them) says the
  same thing;
- off a tag, the version is a pre-release that no tag names. A release
  version is built only on its tag: an untagged `0.3.0` claims to be a release
  that may end up on another commit, and an untagged `0.3.1` passes the
  handshakes against `v0.3.0` just the same, letting a checkout's half pair
  with a release's. The rule's own cases run first, so a change that lets one
  of them through is red here whatever version main carries;
- `wire()`, the Python statement of the rule this relies on, agrees with every
  pair in tools/wire-pairs.json. The filter and the glue are held to the same
  table by filter-golden.py and wasm-parity.mjs.

Needs the tags; a shallow CI checkout fetches them first.

Usage:
    python3 tools/version-gate.py
"""

import sys

import versions

# (version, v* tags, tags on HEAD, refused, awaiting its tag): the release
# rule's cases, as wire-pairs.json is the wire rule's. Awaiting its tag is the
# one refusal the release archives build through, under another name.
RELEASE_CASES = [
    ("0.3.0", ["v0.2.0"], [], True, True),       # a new minor, under review
    ("0.3.0", ["v0.2.0", "v0.3.0"], ["v0.3.0"], False, False),  # on its tag
    ("0.2.1", ["v0.2.0"], [], True, True),       # a patch, under review
    ("0.2.0", ["v0.2.0"], [], True, False),      # a tag, but not HEAD's
    ("0.3.0-dev", ["v0.2.0"], [], False, False),  # main between releases
    ("0.3.0-rc.1", ["v0.2.0", "v0.3.0-rc.1"], [], True, False),  # tag names it
    ("0.3.0-rc.1", ["v0.2.0", "v0.3.0-rc.1"], ["v0.3.0-rc.1"], False, False),
]


def case_problems():
    problems = []
    for v, tags, at_head, refused, awaiting in RELEASE_CASES:
        where = f"{v} with tags {tags}, HEAD at {at_head or 'no tag'}"
        if (versions.release_refusal(v, tags, at_head) is not None) != refused:
            problems.append(f"release rule: {where}, should "
                            f"{'' if refused else 'not '}be refused")
        if versions.awaiting_tag(v, tags) != awaiting:
            problems.append(f"release rule: {where}, should "
                            f"{'' if awaiting else 'not '}be awaiting its tag")
    return problems


def main():
    problems = case_problems() + versions.wire_problems() + versions.check()
    version = versions.version()
    if version:
        problem = versions.release_problem(version)
        if problem:
            problems.append(problem)
    for p in problems:
        print("FAIL: " + p)
    if problems:
        return 1
    print(f"PASS: every declaration says {version}, which this commit may "
          f"carry; the release rule agrees with {len(RELEASE_CASES)} cases and "
          f"wire() with {len(versions.wire_pairs())} pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
