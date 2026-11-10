# flaky-test-detector

Detects flaky tests from your CI run history and automatically opens issues for the worst offenders.

> A test is **flaky** when, on the **same commit**, it passes in one run and fails in another, with no code changes in between.

## Why this matters

Flaky tests cost teams time and trust:

- Pipelines get re-run "just to see if it passes".
- Real failures start being ignored ("probably that test again").
- CI time and cost per pipeline go up.

This project turns the problem into a measurable number: the **flakiness rate per test**.

## How it works

```
CI results  →  Parser  →  Flakiness scoring  →  Report  →  GitHub issue
(JUnit XML / API)         (per test and commit)   (table)    (for the worst ones)
```

1. **Collects** test results from multiple CI runs (JUnit XML or the GitHub Actions API).
2. **Groups** results by test and by commit.
3. **Scores** flakiness: in how many commits the same test had different outcomes.
4. **Ranks** the most unstable tests.
5. **Opens an issue** (optional) for tests above a configurable threshold.

### The scoring

```python
from collections import defaultdict

def flaky_score(runs):
    """runs: list of (test_name, commit_sha, passed)"""
    by_test = defaultdict(lambda: defaultdict(set))
    for name, sha, passed in runs:
        by_test[name][sha].add(passed)

    scores = {}
    for name, commits in by_test.items():
        # flaky = same commit, different results
        flaky = sum(1 for r in commits.values() if len(r) > 1)
        scores[name] = flaky / len(commits)

    return dict(sorted(scores.items(), key=lambda x: -x[1]))
```

**Example:** a test ran on 10 commits and, in 3 of them, both passed and failed on the same commit → score of `0.30` (30%).

## Installation

```bash
git clone https://github.com/<your-username>/flaky-test-detector.git
cd flaky-test-detector
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Requirements: Python 3.10+.

## Usage

### Analyze local JUnit XML files

```bash
python -m flaky_detector analyze ./results/*.xml --threshold 0.1
```

### Analyze GitHub Actions runs

```bash
export GITHUB_TOKEN=<your-token>
python -m flaky_detector analyze --repo owner/repo --last-runs 50
```

### Open issues for flaky tests

```bash
python -m flaky_detector analyze --repo owner/repo --last-runs 50 \
  --threshold 0.1 --create-issues
```

### Example output

```
Test                                     Commits   Flaky   Score
--------------------------------------  -------  ------  ------
tests/checkout/test_payment.py::test_3       20       7    35.0%
tests/login/test_session.py::test_expiry     20       4    20.0%
tests/api/test_orders.py::test_create        20       2    10.0%
```

## Options

| Option | Description | Default |
|---|---|---|
| `--threshold` | Minimum score to consider a test flaky | `0.1` |
| `--last-runs` | Number of CI runs to analyze | `30` |
| `--min-commits` | Minimum commits with data to be included in the ranking | `5` |
| `--create-issues` | Opens one issue per test above the threshold | off |
| `--format` | Report format: `table`, `json` or `markdown` | `table` |

## Using it in GitHub Actions

```yaml
name: Flaky Test Report

on:
  schedule:
    - cron: "0 6 * * 1"   # every Monday, 06:00 UTC
  workflow_dispatch:

jobs:
  detect:
    runs-on: ubuntu-latest
    permissions:
      actions: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: |
          python -m flaky_detector analyze \
            --repo ${{ github.repository }} \
            --last-runs 50 --threshold 0.1 --create-issues
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Project structure

```
flaky-test-detector/
├── flaky_detector/
│   ├── __init__.py
│   ├── __main__.py        # CLI
│   ├── parsers.py         # JUnit XML and GitHub Actions API
│   ├── scoring.py         # flakiness scoring
│   ├── report.py          # table, JSON and markdown output
│   └── issues.py          # GitHub issue creation
├── tests/
├── requirements.txt
└── README.md
```

## Roadmap

- [ ] JUnit XML parser
- [ ] Flakiness scoring per test and commit
- [ ] Table, JSON and markdown reports
- [ ] GitHub Actions API integration
- [ ] Automatic issue creation (without duplicating already-open issues)
- [ ] Example scheduled workflow
- [ ] Suggested quarantine: flag flaky tests so they don't block merges
- [ ] Flakiness rate history over time
- [ ] Support for other CI providers (GitLab CI, CircleCI)

## Limitations

- Flakiness can only be detected when there is **more than one run on the same commit** (re-runs). Without re-runs, a test can't be classified.
- Failures caused by infrastructure (runner timeouts, network drops) may show up as flakiness and should be reviewed manually.

## Contributing

Contributions are welcome. Please open an issue describing your idea before sending a pull request.

## License

MIT
