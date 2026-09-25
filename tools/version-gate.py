#!/usr/bin/env python3
"""The declared version is one string, and honest about where it was built.

Three checks from tools/versions.py:

- the four declarations (Cargo.toml, _extension.yml, the filter's and the
  glue's VERSION) are one version;
- off a tag, the version speaks no wire an existing tag speaks. After `v0.3.0`
  is cut, main must move to a pre-release such as `0.4.0-dev`: `0.3.0` would
  claim to be the release, and an untagged `0.3.1` would pass the handshakes
  against it just the same, letting a checkout's half pair with a release's;
- `wire()`, the Python statement of the rule this relies on, agrees with every
  pair in tools/wire-pairs.json. The filter and the glue are held to the same
  table by filter-golden.py and wasm-parity.mjs.

Needs the tags; a shallow CI checkout fetches them first.

Usage:
    python3 tools/version-gate.py
"""

import sys

import versions


def main():
    problems = versions.wire_problems() + versions.check()
    version = versions.version()
    if version:
        problem = versions.release_problem(version)
        if problem:
            problems.append(problem)
    for p in problems:
        print("FAIL: " + p)
    if problems:
        return 1
    print(f"PASS: every declaration says {version}, whose wire version "
          f"{versions.wire(version)} no other commit's tag speaks, and wire() "
          f"agrees with {len(versions.wire_pairs())} pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
