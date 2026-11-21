"""Generate synthetic JUnit XML files for trying out the detector.

    python scripts/generate_junit.py --commits 40 --runs 3 --out results

Each commit gets several runs (re-runs). Tests have a hidden behaviour:
stable, flaky (random failure rate), broken-on-some-commits (fails in every
run, so it is NOT flaky) or skipped. Output is deterministic for a given --seed.

With --env NAME=v1,v2 every run is written once per value (a CI matrix: same
commit and run id, one file per leg, tagged with a NAME property). A few stable
tests then become "config-dependent": they always fail in one value and always
pass in the others, so they are NOT flaky. Analyze with --env-property NAME.
Without --env the output is identical to what it was before this option existed.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

MODULES = {
    "tests.checkout.test_payment": 14, "tests.checkout.test_cart": 12,
    "tests.login.test_session": 10, "tests.login.test_oauth": 8,
    "tests.api.test_orders": 16, "tests.api.test_users": 12,
    "tests.db.test_migrations": 6, "tests.search.test_index": 10,
    "tests.notifications.test_email": 8, "tests.utils.test_dates": 14,
}
FLAKY_MESSAGES = [
    "AssertionError: timeout waiting for gateway",
    "ConnectionError: connection reset by peer",
    "AssertionError: expected 200, got 503",
    "TimeoutError: operation timed out after 30s",
    "AssertionError: race condition on shared state",
]


def build_tests(rng: random.Random):
    tests = []
    for module, n in MODULES.items():
        for i in range(1, n + 1):
            roll = rng.random()
            if roll < 0.12:
                kind, p = "flaky", rng.choice([0.05, 0.1, 0.2, 0.35, 0.5])
            elif roll < 0.17:
                kind, p = "broken", rng.uniform(0.1, 0.3)  # share of commits it is broken on
            elif roll < 0.21:
                kind, p = "skipped", 0.0
            else:
                kind, p = "stable", 0.0
            tests.append((module, f"test_{i}", kind, p))
    return tests


def pick_config_dependent(tests, env_values, seed, share=0.08):
    """Stable tests that always fail in one env value. Own RNG: the main stream is untouched."""
    rng = random.Random(seed + 1)
    return {
        (m, n): rng.choice(env_values)
        for m, n, kind, _ in tests
        if kind == "stable" and rng.random() < share
    }


def render(commit, run_id, attempt, results, ts, env=None):
    fails = sum(1 for r in results if r[1] == "failure")
    errs = sum(1 for r in results if r[1] == "error")
    skips = sum(1 for r in results if r[1] == "skipped")
    out = [
        '<?xml version="1.0" encoding="utf-8"?>', "<testsuites>",
        f'  <testsuite name="pytest" errors="{errs}" failures="{fails}" skipped="{skips}" '
        f'tests="{len(results)}" time="{sum(r[3] for r in results):.3f}" timestamp="{ts}">',
        "    <properties>",
        f'      <property name="commit_sha" value="{commit}"/>',
        f'      <property name="run_id" value="{run_id}"/>',
        *([f'      <property name={quoteattr(env[0])} value={quoteattr(env[1])}/>'] if env else []),
        "    </properties>",
    ]
    for cls, kind, msg, t, name in results:
        head = f'    <testcase classname="{cls}" name="{name}" time="{t:.3f}"'
        if kind == "pass":
            out.append(head + "/>")
        elif kind == "skipped":
            out.append(head + '><skipped message="requires external service"/></testcase>')
        else:
            out.append(f"{head}><{kind} message={quoteattr(msg)}>{escape(msg)}</{kind}></testcase>")
    out += ["  </testsuite>", "</testsuites>", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commits", type=int, default=40)
    ap.add_argument("--runs", type=int, default=3, help="runs (re-runs) per commit")
    ap.add_argument("--out", default="results")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--env", metavar="NAME=v1,v2",
                    help="write one file per value per run (a CI matrix), e.g. python=3.12,3.13")
    args = ap.parse_args()

    env_name, env_values = None, [None]
    if args.env:
        env_name, _, raw = args.env.partition("=")
        env_values = [v.strip() for v in raw.split(",") if v.strip()]
        if not env_name or len(env_values) < 2:
            ap.error("--env needs a name and at least two values, e.g. python=3.12,3.13")

    rng = random.Random(args.seed)
    tests = build_tests(rng)
    config_fail = pick_config_dependent(tests, env_values, args.seed) if env_name else {}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_id = 20000
    written = 0

    for c in range(args.commits):
        sha = f"gen{c:03d}{rng.getrandbits(32):08x}"
        broken_here = {(m, n) for m, n, k, p in tests if k == "broken" and rng.random() < p}
        for attempt in range(1, args.runs + 1):
            run_id += 1
            ts = f"2026-11-{1 + c % 28:02d}T{8 + attempt:02d}:00:00"
            for env_value in env_values:  # one leg per env value; a single pass without --env
                results = []
                for module, name, kind, p in tests:
                    t = rng.uniform(0.005, 2.5)
                    if kind == "skipped":
                        results.append((module, "skipped", "", 0.0, name))
                    elif env_name and config_fail.get((module, name)) == env_value:
                        results.append((module, "failure",
                                        f"AssertionError: fails on {env_name}={env_value}", t, name))
                    elif (module, name) in broken_here:
                        results.append((module, "failure", "AssertionError: regression in this commit", t, name))
                    elif kind == "flaky" and rng.random() < p:
                        tag = "error" if rng.random() < 0.2 else "failure"
                        results.append((module, tag, rng.choice(FLAKY_MESSAGES), t, name))
                    else:
                        results.append((module, "pass", "", t, name))
                suffix = f"_{env_value}" if env_name else ""
                env = (env_name, env_value) if env_name else None
                (out / f"run_{sha}_{attempt}{suffix}.xml").write_text(
                    render(sha, run_id, attempt, results, ts, env))
                written += 1
    print(f"wrote {written} files ({len(tests)} tests each) to {out}/")


if __name__ == "__main__":
    main()
