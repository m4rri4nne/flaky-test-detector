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

## 3. Roadmap

Ordered by value ÷ effort and by dependency. Each item lists the comments it answers.

### Phase 1: correctness (stop wrong flags)  · small
- **R-1a. Environment dimension.** Read env properties from JUnit (`python`, `os`, `job`, runner
  label, or a configurable list) and, on GitHub, derive a fingerprint from the job/artifact name.
  Score within `(test, commit_sha, env)`. Report cross-environment disagreement as a separate
  "config-dependent" category, not as flaky. *(#3, #5, #8, #12, #2, #19)*
  - Do **not** key on `run_id` (re-runs share it).
  - Test: fixture with one stable-pass and one stable-fail job on the same SHA ⇒ not flaky,
    listed as config-dependent. Add to `tests/test_scoring.py` and the sample generator.
- **R-1b. Read in-job retries.** Treat `<flakyFailure>`, `<flakyError>`, `<rerunFailure>`,
  `<rerunError>` as a failed attempt followed by the final outcome (record both). *(#18)*
- **R-1c. Run count.** Add `runs` per test and per commit to `TestScore` and all three report
  formats. *(#16)*

### Phase 2: trustworthy statistics  · small–medium
- ***R-2. Confidence.*** Add a Wilson interval (and an optional recency weight) to the score;
  rank by the lower bound or show it next to the score. Keeps `min_commits` but softens the
  "new test at 0.2" artefact. *(#15, #17)*
- **R-4. Message normalization and counts.** Replace numbers/ids/durations/hex with
  placeholders, store `{message: count}` instead of a distinct list, keep the raw first example.
  Bump the JSON schema (`error_messages` → keep the old key for compatibility, add
  `error_message_counts`). *(#6, #15)*

### Phase 3: richer evidence for the agent  · medium
- **R-3. Send the agent only what it needs.** Filter `fetch_json_report` to flaky tests (and
  drop `commits_where_flaky` unless asked). This makes the token-budget claim in #1 actually
  true. Also fix the README drifts. *(#1)*
- **R-5. Traces and duration.** Keep a truncated stack trace and per-test duration stats
  (median, p95, variance across the flaky commits). Optionally pass runner/job labels. Lets the
  agent separate "slow runner" from "race condition". *(#4, #13)*
- **R-6. Deterministic trend.** A `trend` command (or a report section) comparing the last N
  JSON reports: score delta per test, "rising" flag when it crosses a configurable slope before
  the threshold. Needs reports to persist: today the workflow only uploads them as artifacts, so
  commit them to a branch or download previous artifacts first. *(#7)*

### Phase 4: more signal  · medium–large
- **R-7. Scheduled reruns.** A workflow that reruns `main` (or the last K commits) N times on a
  schedule, uploading JUnit artifacts with distinct names per attempt. Document the runner-minute
  cost and make N and cadence inputs. *(#1, #20, #2)*
- **R-8. Confirm step.** A `confirm` command / workflow job that reruns only the flagged tests N
  times and records the pass rate per test. Gives the "run 10× before the agent investigates"
  behaviour that comment #2 credits. *(#2)*
- **R-10. Test source for the agent.** Attach the source of each flagged test (bounded length,
  resolved from `classname` + repo checkout) so root causes can cite code, not just messages.
  *(#20)*

### Phase 5: quality of the AI step  · medium
- **R-9. Evaluation harness.** Extend `generate_junit.py` so each flaky test carries a ground-truth
  cause (timeout, race, network, order) and emits messages consistent with it. Score the agent on
  evidence alignment (cites the right messages / says "unknown") separately from readability, and
  run it across models via Strands' model providers (Gemini today; add one other hosted and one
  local model). *(#9, #6, #10)*

### Later / optional
- **R-11. Reproduce mode for order dependence.** Replay with fixed seeds, bisect to the minimal
  offender pair, emit the seed for CI. Language/runner specific, so start with pytest only. *(#14, #4)*
- **R-12. Other CI sources.** A Jenkins fetcher behind the same interface as `github.py`. *(#19)*
- **R-13. Quarantine suggestions.** Already on the README roadmap; build on R-1 and R-2 so only
  high-confidence, non-config-dependent tests are suggested. *(#15)*

### Suggested order
`R-1a/b/c → R-4 → R-2 → R-3 → R-5 → R-6 → R-9 → R-7/R-8 → R-10 → R-13 → R-11/R-12`

R-1 first because it removes false positives (the credibility problem four commenters raised);
R-3 is a one-hour fix that makes a claim in the article accurate; R-7/R-8 come later because
they cost CI minutes and depend on a clean scoring model.

## 4. Replies worth posting
- #12 (Oleksandr): thank them, but explain that GitHub re-runs keep the same `run_id`, so the
  missing dimension is environment, not run.
- #18 (Idan): admit the parser reads only the final `<failure>`/`<error>` and that retry elements
  are planned (R-1b).
- #2 (IICTP) and #20: clarify whether the 10× confirmation is implemented or planned (R-8).
