#!/usr/bin/env python3
"""Write one commit status per gate, so a red run can say WHICH gate went red.

Why this exists
---------------
On this instance a failed run is legible as "failed" and nothing else. The
`actions/runs`, `actions/jobs` and `actions/workflows` endpoints all return 404
on Forgejo 11.0.16, and `actions/tasks` -- the one that answers -- carries a
status with no log text. Locating a failure has therefore cost, twice, work that
should not have been necessary: once a manual re-run of the entire job inside
`azura-ci:latest` to discover it was the fifth step (`6e416d3`), and once an
argument from step timings to place a deliberate red (#28). Every future red
would bill the same again, to the reviewer rather than to whoever broke it.

The commit status API does answer, and CI already writes one status for the job.
This writes one per gate, on the same commit, so
`/api/v1/repos/{owner}/{repo}/commits/{sha}/statuses` answers the question
directly -- through the API this version actually serves, rather than waiting
for an instance upgrade nobody in this repository controls.

How it knows the gates
----------------------
From `steps` (passed in as `STEPS`), which holds an entry per step that declared
an `id` in ci.yml. The ids ARE the gate list: there is no second copy here to
keep in step, and a gate added later reports itself the day its id is written.

Run by the last step of .forgejo/workflows/ci.yml, under `if: always()`.
"""

import json
import os
import sys
import urllib.error
import urllib.request

# Gitea/Forgejo's commit status states. `skipped` and `cancelled` are neither a
# pass nor a failure, and calling them either would be a lie in the one place a
# reviewer looks first.
STATE = {
    "success": "success",
    "failure": "failure",
    "cancelled": "warning",
    "skipped": "warning",
}


def main():
    token = os.environ.get("STATUS_TOKEN", "").strip()
    sha = os.environ.get("HEAD_SHA", "").strip()
    server = os.environ.get("GITHUB_SERVER_URL", "").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    steps = json.loads(os.environ.get("STEPS") or "{}")

    if not token:
        # Said plainly rather than skipped in silence: without a token this
        # reporter does nothing at all, and a reviewer who sees no per-gate
        # statuses should know whether that is the reporter or the gates.
        print("no STATUS_TOKEN in this run -- no per-gate statuses will exist. "
              "If this run is red, locating it is back to reading timings.")
        return 1
    if not (sha and server and repo):
        print(f"missing context: sha={sha!r} server={server!r} repo={repo!r}")
        return 1

    # Forgejo also keys every step WITHOUT an id by its position, so `steps`
    # arrives holding "0", "1", "13" beside the named ones. `gate/13` on a
    # commit tells a reviewer nothing it did not already know, and five of them
    # bury the nine that do. An id is how a step says it is a gate.
    named = {k: v for k, v in steps.items() if not k.isdigit()}

    failures, posted = [], 0
    for name, step in sorted(named.items()):
        outcome = (step or {}).get("outcome")
        if not outcome:
            continue
        state = STATE.get(outcome, "warning")
        if state == "failure":
            failures.append(name)
        body = json.dumps({
            "state": state,
            "context": f"gate/{name}",
            "description": f"{outcome} in this run",
            "target_url": f"{server}/{repo}/actions",
        }).encode()
        request = urllib.request.Request(
            f"{server}/api/v1/repos/{repo}/statuses/{sha}",
            data=body, method="POST",
            headers={"Authorization": f"token {token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            posted += 1
            print(f"  gate/{name}: {state}")
        except urllib.error.HTTPError as error:
            print(f"  gate/{name}: POST failed, {error.code} "
                  f"{error.read()[:200]!r}")
        except OSError as error:
            print(f"  gate/{name}: POST failed, {error}")

    if posted != sum(1 for s in named.values() if (s or {}).get("outcome")):
        # A reporter that cannot report is a defect worth a red of its own. It
        # cannot mask a gate failure: the gate's own step has already failed by
        # the time this runs.
        print("not every gate could be reported; the statuses are incomplete")
        return 1
    print(f"posted {posted} gate statuses on {sha[:8]}"
          + (f"; failed: {', '.join(failures)}" if failures else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
