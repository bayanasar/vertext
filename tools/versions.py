"""The version declarations, read once, and the rules that compare them.

Six files declare a version, and a filter, glue or binding built from one
checkout must refuse a binary or library built from another:

    Cargo.toml             [workspace.package] version -- what the binary, the
                           wasm module and the native library report
    _extension.yml         what Quarto installs the filter by
    vertext.lua            VERSION, what the filter compares against
    vertext.mjs            VERSION, what the glue compares against
    pubspec.yaml           what the Dart binding is resolved by
    vertext.dart           version, what the Dart binding compares against

Everything else that talks about the declarations points here rather than
listing them, so adding one is a change to this file.

They are typed by hand and must be one string; `check()` says where they
disagree. Every tool reads them here, so there is one parser per file and a
file that moves its declaration fails in one place.

The handshake compares WIRE versions, and `wire()` is the rule, written the
same way in vertext.lua, vertext.mjs and vertext.dart. tools/wire-pairs.json
holds it as data; `wire_problems()` checks `wire()` against it, and
filter-golden.py, wasm-parity.mjs and the Dart binding's vertext_test.dart
check the other three:

- A release (`0.3.1`) speaks its MAJOR.MINOR (`0.3`): a patch release may not
  change the wire protocol, an export or what the source map means, so patch
  releases of one minor accept each other.
- A pre-release (`0.4.0-dev`) speaks its whole version. Main carries the next
  minor's pre-release from the day after a tag, so a half built from a
  checkout is refused by a half from any release, including the release of the
  same minor it is heading for. The cost: two checkouts of main between the
  same two tags both say `0.4.0-dev` and accept each other.

A release version is only honest on its tag, so off a tag `release_problem()`
refuses every release version, a new minor's included: between setting
`0.3.0` and cutting `v0.3.0`, every commit that lands builds halves claiming
to be 0.3.0, and if the tag goes on a later commit they pair with the release.
A release commit is therefore red here until its tag is pushed, which happens
only once its review approves; the tag push runs CI again on the same commit,
with HEAD on the tag (docs/ARCHITECTURE.md gives the order). Off a tag a
pre-release passes unless a tag already names it (`v0.3.0-rc.1`), which is the
same wire comparison: a pre-release speaks only its whole version.

One refusal is a state rather than a mistake: a release version that no tag
names yet, which is what a release commit under review carries. The release
archives then build and check everything and withhold only the release name,
so the review sees the packaging work on the commit it approves. A release
version whose tag is on another commit is a mistake, and refused outright.
`archive_suffix()` is that three-way rule, and both archives take their name
from it rather than each working it out.
"""

import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(path, pattern, flags=re.MULTILINE):
    found = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), flags)
    return found and found.group(1)


def declared():
    """{declaration: version or None}, by the name a message should use."""
    return {
        "Cargo.toml": _read("Cargo.toml",
                            r'^\[workspace\.package\][^\[]*?^version\s*=\s*"([^"]+)"',
                            re.MULTILINE | re.DOTALL),
        "_extension.yml": _read("extensions/vertext/_extension.yml", r"^version:\s*(\S+)\s*$"),
        "vertext.lua": _read("extensions/vertext/vertext.lua", r'^local VERSION = "([^"]+)"'),
        "vertext.mjs": _read("examples/wasm/vertext.mjs", r"^export const VERSION = '([^']+)';$"),
        "pubspec.yaml": _read("bindings/dart/pubspec.yaml", r"^version:\s*(\S+)\s*$"),
        "vertext.dart": _read("bindings/dart/lib/vertext.dart", r"^const version = '([^']+)';$"),
    }


def check():
    """Why the declarations are not one version, or [] when they are."""
    found = declared()
    missing = [name for name, v in found.items() if not v]
    if missing:
        return [f"versions: no declaration found in {', '.join(missing)}"]
    if len(set(found.values())) != 1:
        return ["versions: the declarations disagree: " +
                ", ".join(f"{name} {v}" for name, v in found.items())]
    return []


def version():
    """The one version, or None when `check()` has something to say."""
    return None if check() else declared()["Cargo.toml"]


def wire(v):
    """The wire version a half with version `v` speaks."""
    return v if "-" in v else ".".join(v.split(".")[:2])


def wire_pairs():
    """The rule as data, shared with the filter's and the glue's tests."""
    return json.loads((ROOT / "tools" / "wire-pairs.json").read_text())["pairs"]


def wire_problems():
    """Where `wire()` disagrees with tools/wire-pairs.json, or []."""
    return [f"wire rule: {p['ours']} and {p['theirs']} should "
            f"{'' if p['agree'] else 'not '}agree ({p['why']})"
            for p in wire_pairs()
            if (wire(p["ours"]) == wire(p["theirs"])) != p["agree"]]


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, check=True).stdout.split()


NO_TAGS = "no v* tags are visible, so nothing can be checked: fetch the tags"


def _tags():
    """(v* tags, tags on HEAD)."""
    return _git("tag", "--list", "v*"), _git("tag", "--points-at", "HEAD")


def release_problem(v):
    """Why version `v` may not be built at HEAD, or None.

    Needs the tags: in a shallow CI checkout, fetch them first. No tags at all
    is an error rather than a pass, because a checkout without tags would let
    every version through.
    """
    tags, at_head = _tags()
    return release_refusal(v, tags, at_head) if tags else NO_TAGS


def release_refusal(v, tags, at_head):
    """`release_problem()` without git: `tags` are the v* tags, `at_head`
    those on HEAD. version-gate.py runs its cases through this."""
    if f"v{v}" in at_head:
        return None
    if f"v{v}" in tags:
        return (f"version {v} is already tagged v{v} on another commit: move "
                f"to the next pre-release")
    if "-" not in v:
        return (f"version {v} is a release and HEAD is not tagged v{v}: a "
                f"release version is built only on its tag. Under review this "
                f"is expected, and every other gate must pass; once the review "
                f"approves, tag this commit and push the tag "
                f"(docs/ARCHITECTURE.md), or move to a pre-release")
    speaking = [t for t in tags if wire(t[1:]) == wire(v)]
    if speaking:
        return (f"version {v} is already tagged {', '.join(speaking)}, and "
                f"HEAD is not that tag: move to the next pre-release")
    return None


UNTAGGED = "+untagged"


def archive_suffix(v, tags, at_head):
    """What a release archive for `v` carries after the version in its name,
    and why: `("", None)` when `release_refusal()` lets `v` through,
    `(UNTAGGED, refusal)` when the only refusal is that `v` is a release no
    tag names yet -- a release commit under review, built and checked in
    full under a name no release uses -- and `(None, refusal)`, no archive,
    for anything else. version-gate.py runs its cases through this."""
    refusal = release_refusal(v, tags, at_head)
    if refusal is None:
        return "", None
    if "-" not in v and f"v{v}" not in tags:
        return UNTAGGED, refusal
    return None, refusal


def archive_suffix_at_head(v):
    """`archive_suffix()` against the repository's tags; no archive when
    none are visible, since then nothing about `v` is known."""
    tags, at_head = _tags()
    return archive_suffix(v, tags, at_head) if tags else (None, NO_TAGS)
