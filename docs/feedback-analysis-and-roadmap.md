# Dev.to feedback: analysis and roadmap

Source: 23 comments on the article (collected 2026-11-12). Each one was checked against the
code as of commit `65ae96a`.

Verdicts: **Valid** (real gap, worth doing) · **Partly** (right idea, but something is off or
already covered) · **Already covered** · **Out of scope** · **No action**.

## 1. What the code does today (facts the comments were checked against)

| Area | Fact | Where |
|---|---|---|
| Grouping key | `(test name, commit_sha)`. Nothing else. | `scoring.py:42-47` |
| `run_id` | Parsed, **never used** in scoring. | `parsers.py:152`, `scoring.py` |
| Environment | Not captured. Only `commit_sha` / `run_id` properties are read. | `parsers.py:50-51` |
| Retries in the job | Only `<error>`, `<failure>`, `<skipped>` are read. Surefire-style `<flakyFailure>` / `<flakyError>` / `<rerunFailure>` children are ignored, so a retried-then-passed test counts as a plain pass. | `parsers.py:132-141` |
| Error messages | Distinct strings, first-seen order, **no counts, no normalization**. Stack trace text is only used if the `message` attribute is missing. | `scoring.py:48-49`, `parsers.py:140` |
| Duration | `time` is parsed into `TestResult` but never reaches a score or a report. | `parsers.py:144-146` |
| Score | `flaky_commits / commits`. No confidence interval, no recency weighting, no run counts in the report. | `scoring.py:28-30` |
| Re-runs on GitHub | A re-run keeps the **same `run_id`** (new attempt). The fetcher tags every result of a run with that one id. | `github.py:160-175` |
| Agent input | `fetch_json_report` returns the **whole** report (all eligible tests, each with `commits_where_flaky`), not only the flaky ones. | `agent.py:74-75` |
| Trend | Only the LLM compares reports across a period. No deterministic trend. | `agent.py:64-71` |
| Reproduction | The tool never runs tests; it only reads history. | whole repo |
| Fetchers | GitHub Actions only. The parser is generic JUnit. | `github.py` |

Two doc drifts found on the way: the README says `export_analysis` writes to `reports/` but the
code writes to `analysis/`; and it says the agent question is hard-coded, but `main()` now takes a
`period` argument.

## 2. Comment by comment

| # | Author | Point | Verdict | Why |
|---|---|---|---|---|
| 1 | Dean Lee | One run per SHA ⇒ flaky tests invisible; reruns cost runner minutes. Scoring is split from the agent, so only the 12 flagged tests reach the prompt. | **Valid** (1st half) / **Partly** (2nd) | The README already lists the limitation; the fix (scheduled reruns) is not built. The token claim is only half true: the agent gets the full report, not just the 12 flaky tests (see R-3). |
| 2 | IICTP | Where does the score mislead (runner, time of day)? Also credits a "run flagged tests 10×" step. | **Valid** (question) / **Not in repo** (10× rerun) | Same root as the environment gap. The confirm-by-rerun step does not exist in this repository, so either it is in the article only or it should be built (R-8). |
| 3 | Marcus Kim | Pass on 3.12 / fail on 3.13 at the same SHA is flagged flaky. Group by runtime/OS/lock; add a fixture. | **Valid, highest priority** | Confirmed false positive: a matrix build uploads several artifacts under one run and one SHA, and the key ignores the environment. |
| 4 | mp3sss | Trust erosion; order/fixture-dependent flakes; Electron E2E; keep failure traces before AI pass. | **Partly** | Trust point is the project's premise. Keeping traces is valid (R-5). Order dependence is out of reach for a history reader (see #16). |
| 5 | OneLifeVibe | Echoes Marcus; says env dimension should sit "alongside commit_sha and run_id you already require". | **Valid** | Same as #3. Small correction: scoring does not use `run_id` today. |
| 6 | Maciek Chmura | Count + normalize error messages (strip numbers/ids/durations); infra vs test cause. | **Valid** | Today `"after 30s"` and `"after 31s"` are two strings and no frequency is available. Easy and cheap (R-4). The "Gemini mixed infra/test cause" answer is mostly a data issue: the generator picks messages at random, not tied to a cause. |
| 7 | ArgumentMoney8117 | Track score over time, flag creeping tests (0.02 → 0.1). | **Valid** | JSON reports already hold the data, but nothing computes a trend except the LLM (R-6). |
| 8 | Paul Lovelace | Tag environment into the key, or does grouping explode? | **Valid** (answers #3) | It won't explode: a CI matrix has a handful of legs. Use env as a separate dimension and report cross-env disagreement separately. |
| 9 | Raju Dandigam | Seed failures with known causes; score evidence alignment separately from readability when comparing models. | **Valid** | Generator hides flaky/broken/stable but not the cause, so there is no ground truth to score against (R-9). |
| 10 | Kürşat Yılmaz | Agent wrappers add latency/failure; prefer local C++/llama.cpp/vLLM. | **Out of scope** (mostly) | The agent is one optional offline call per report; latency is irrelevant. The only useful piece is model-pluggability for the model comparison already planned (R-9). |
| 11 | BMayhew | Will include it in a newsletter. | **No action** | — |
| 12 | Oleksandr | Group by `(commit_sha, run_id)` first. | **Partly, and the fix is wrong for GitHub** | The diagnosis (no environment dimension) is right. The remedy would break detection: a GitHub re-run keeps the same `run_id`, so grouping by run would split nothing and hide exactly the re-runs we need. The missing dimension is *environment*, not run. |
| 13 | Mudassir Khan | Noisy-neighbour runners make timing tests look flaky; does the agent see runner/resource metadata? | **Valid** | Agent sees only message strings. `time` is parsed and dropped. Duration variance and runner labels would let the agent separate infra noise (R-5). His first sentence (A fails / B passes = regression) matches the current design. |
| 14 | Nan | Order-dependent flakes: replay with seeds, bisect to the offending pair, pin the seed in CI. | **Valid idea, out of scope for the detector** | The tool only reads history and cannot reproduce. Worth a late, optional "reproduce" mode (R-11). Cheap part now: let the agent *suggest* this when messages suggest shared state. |
| 15 | xcl | Small-sample calibration (confidence interval, recency weighting); group by failure mode; quarantine top scorers, observe the rest. | **Valid (3 parts)** | Interval and recency are not implemented (R-2). Failure-mode grouping already exists in the agent prompt but is not deterministic (R-4). Quarantine is already on the README roadmap. Note the example compares runs, but the score counts commits. |
| 16 | AIFix | Show runs per commit so readers see how much evidence backs a score. | **Valid, trivial** | Report has `commits` only. Add `runs` (R-1). |
| 17 | Kartik N V J K | 1 flaky commit flags a test until it has >10 commits; a new test's 0.2 reads as twice an old test's 0.1. | **Correct observation** | Arithmetic checks out (1/5, 1/10 flag; 1/11 does not). Not a bug, but it is the argument for R-2 (confidence interval). |
| 18 | Idan Shalem | In-job retries may be written as a single pass. Does the parser see the failed attempts? | **Valid, real gap** | It does not: `<flakyFailure>`/`<rerunFailure>` are ignored (R-1). This also partly solves the "no reruns" visibility problem for suites that already retry. |
| 19 | (anonymous, DevOps) | Track failure frequency, duration, env, history; integrate Jenkins/Actions; how to tell flaky from regression without false positives. | **Partly** | Actions integration exists; the parser is generic, only the fetcher is GitHub-specific (Jenkins fetcher is R-12). Flaky vs regression is exactly the same-commit rule; the false-positive risk is the env gap (R-1). Duration/frequency overlap #13 and #7. |
| 20 | (anonymous, last) | Scheduled reruns of main; give the agent test source so it can go beyond error messages. | **Valid (both)** | Same as #1 (R-7). Test source for the agent is a good, bounded add (R-10). |

## 3. What was implemented

| Item | What | Answers |
|---|---|---|
| R-1a | Environment dimension; cross-environment disagreement reported as "config-dependent" (never keyed on `run_id`) | #3, #5, #8, #12, #2, #19 |
| R-1b | In-job retries (`flakyFailure`, `flakyError`, `rerunFailure`, `rerunError`) read as failed attempts | #18 |
| R-1c | Run counts per test and per flaky commit | #16 |
| R-2 | Wilson interval; ranking and threshold use the lower bound | #15, #17 |
| R-3 | Agent receives only flaky tests; README drifts fixed | #1 |
| R-5 | Duration median/p95 and truncated stack trace per test | #4, #13 |
| R-6 | `trend` command for rising tests | #7 |
| R-13 | Quarantine suggestions (flaky, lower bound >= 30%, not config-dependent) | #15 |

## Not planned

The project is being finalized without these: error message normalization and counts (R-4),
scheduled reruns (R-7), a `confirm` step (R-8), test source for the agent (R-10), an evaluation
harness across models (R-9), reproduce mode for order dependence (R-11) and a Jenkins fetcher
(R-12). The related comments (#1, #2, #6, #9, #10, #14, #19, #20) remain valid ideas, but are out
of the delivered scope.

## 4. Replies worth posting
- #12 (Oleksandr): thank them, but explain that GitHub re-runs keep the same `run_id`, so the
  missing dimension is environment, not run.
- #18 (Idan): admit the parser reads only the final `<failure>`/`<error>` and that retry elements
  are now read (R-1b).
- #2 (IICTP) and #20: clarify that the 10× confirmation and scheduled reruns are not implemented.
