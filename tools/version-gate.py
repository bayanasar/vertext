#!/usr/bin/env python3
"""The declared version is one string, and honest about where it was built.

Two checks from tools/versions.py:

- the four declarations (Cargo.toml, _extension.yml, the filter's and the
  glue's VERSION) are one version;
- a version an existing tag already names is only built at that tag. After
  `v0.3.0` is cut, main must move to `0.4.0-dev`: otherwise every build from
  main says 0.3.0, and the handshakes, which compare versions, let a checkout's
  half pair with a release's.

Needs the tags; a shallow CI checkout fetches them first.

Usage:
    python3 tools/version-gate.py
"""

import sys

import versions


def main():
    problems = versions.check()
    if not problems:
        version = versions.version()
        problem = versions.release_problem(version)
        if problem:
            problems.append(problem)
    for p in problems:
        print("FAIL: " + p)
    if problems:
        return 1
    print(f"PASS: every declaration says {version}, which is "
          + ("a pre-release" if "-" in version else "a release") + " and no other commit's tag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
