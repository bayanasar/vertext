# docs

Four kinds of writing live in this repository, and mixing them is what makes
documentation rot. Each answers one question and nothing else:

| Where | Question | Ages? |
|---|---|---|
| `/README.md` | What is this and how do I run it? | No — it must stay true for a stranger arriving today |
| `/PROGRESS.md` | Which claims have actually been run, and which have not? | Yes — dated on purpose, rewritten at every seal |
| `docs/*.md` | Why is it built this way? | Slowly — a design outlives the code that expresses it |
| Doc comments in `crates/` | What does this function do? | With the code, in the same commit |

The rule that follows: **a statement belongs in exactly one of them.** A
mechanism explained in a doc comment is not re-explained here; a run result is
never quoted outside `PROGRESS.md`, where it carries its evidence. Two copies of
a fact drift, and the reader cannot tell which half is stale.

## What is here

- [`OVERVIEW.md`](OVERVIEW.md) — the family. One engine and the documents that
  consume it, how each consumer binds to it, and where the whole thing stands.
  Start here if you have never seen this project.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the layout works end to end: the
  slot model, the orientation measure, progression, the document model, and the
  wire protocol between the Quarto filter and the binary.

## API reference

The API documentation is the doc comments in `crates/`, which are the source of
truth and travel in the same commit as the code they describe. `rustdoc` renders
them; it does not add to them.

```sh
./docs/build-api.sh          # cargo doc --no-deps, then prints the entry point
```

Output lands in `target/doc/`, which is git-ignored. Generated HTML is not
committed: it is derived, it is large, and a committed copy is stale the moment
anyone edits a doc comment — the same drift class as a vendored filter running
ahead of its pinned binary, which this project has already been bitten by once.
Read `crates/vertext-core/src/lib.rs` directly if you have no toolchain; it is
written to be read that way.
