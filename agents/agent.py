import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from strands import Agent, tool
from strands.models.gemini import GeminiModel

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
ANALYSIS_DIR = Path(__file__).resolve().parent.parent / "analysis"

PERIODS = {
    "last_24_hours": timedelta(hours=24),
    "last_7_days": timedelta(days=7),
    "last_30_days": timedelta(days=30),
    "last_90_days": timedelta(days=90),
    "last_180_days": timedelta(days=180),
    "last_365_days": timedelta(days=365),
}


def _load_reports() -> list[tuple[datetime, dict]]:
    """Load every JSON report in reports/, sorted oldest -> newest by generated_at (UTC)."""
    found: dict[datetime, dict] = {}
    for path in REPORTS_DIR.glob("flaky-report*.json"):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        when = datetime.fromisoformat(data["generated_at"])
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        found[when.astimezone(timezone.utc)] = data
    return sorted(found.items(), key=lambda item: item[0])


@tool
def fetch_json_report(timestamp: str = "", period: str = "") -> dict:
    """Fetch flaky-test JSON report data so it can be analysed.

    Use this tool whenever the user asks about flaky tests, scores, trends or past reports.
    All timestamps are UTC, in the format YYYY-MM-DDTHH:MM:SS.

    Behaviour:
    - period given: return every report generated inside that period (timestamp is ignored).
    - timestamp as YYYY-MM-DDTHH:MM:SS: return the report generated at exactly that time.
    - timestamp as YYYY-MM-DD: return the latest report generated on that date.
    - nothing given: return the latest report available.
    Raises FileNotFoundError if no matching report exists.

    Args:
        timestamp: Report timestamp, YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD (UTC). Leave empty for the latest report.
        period: One of "last_24_hours", "last_7_days", "last_30_days", "last_90_days",
            "last_180_days", "last_365_days". Leave empty when not asking for a period.

    Returns:
        dict: A single report (generated_at, threshold, flaky_count, flaky_rate, tests, ...), or for a
        period, {"period": ..., "count": N, "reports": [report, ...]} ordered oldest to newest.
    """
    reports = _load_reports()
    if not reports:
        raise FileNotFoundError(f"No reports found in {REPORTS_DIR}.")

    if period:
        if period not in PERIODS:
            raise ValueError(f"Invalid period {period!r}. Use one of: {', '.join(PERIODS)}.")
        since = datetime.now(timezone.utc) - PERIODS[period]
        selected = [data for when, data in reports if when >= since]
        if not selected:
            raise FileNotFoundError(f"No reports found for {period}.")
        return {"period": period, "count": len(selected), "reports": selected}

    if not timestamp:
        return reports[-1][1]

    if "T" in timestamp:
        target = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        for when, data in reports:
            if when.replace(microsecond=0) == target:
                return data
    else:
        day = datetime.strptime(timestamp, "%Y-%m-%d").date()
        same_day = [data for when, data in reports if when.date() == day]
        if same_day:
            return same_day[-1]
    raise FileNotFoundError(f"Report for timestamp {timestamp} not found.")


@tool
def export_analysis(summary: str, root_causes: str, recommendations: str = "",
                    timestamp: str = "", title: str = "Flaky tests analysis") -> str:
    """Save your analysis of the flaky tests as a Markdown report file.

    Call this tool ONCE, after you have fetched and analysed the report. The file also gets an
    "Evidence" table with the raw error messages of every flaky test, added automatically.

    Args:
        summary: Markdown summary: how many tests are flaky, the flaky rate, the worst tests and
            their scores, and any trend if several reports were compared.
        root_causes: Markdown with the possible root cause(s) of the flakiness, inferred from the
            error messages. Group tests by cause (e.g. timeouts / slow dependency, race condition
            on shared state, network or gateway instability, order dependency, bad test data).
            For each cause say which tests it affects, quote the error messages that support it
            and give a confidence level (high/medium/low). If a test has no error messages, say
            the cause cannot be determined from the data instead of guessing.
        recommendations: Markdown with concrete next steps to fix each cause.
        timestamp: Timestamp (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD, UTC) of the analysed report, used to
            attach the error-message evidence. Leave empty for the latest report.
        title: Short title for the report.

    Returns:
        str: The path of the Markdown file that was written.
    """
    if not summary.strip() or not root_causes.strip():
        raise ValueError("summary and root_causes are required; write them before exporting.")
    now = datetime.now(timezone.utc)
    lines = [
        f"# {title.strip() or 'Flaky tests analysis'}",
        "",
        f"_Generated by AI agent: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC_",
        "",
        "## Summary",
        "",
        summary.strip(),
        "",
        "## Possible root causes",
        "",
        root_causes.strip(),
        "",
    ]
    if recommendations.strip():
        lines += ["## Recommendations", "", recommendations.strip(), ""]

    try:
        data = fetch_json_report(timestamp=timestamp)
    except (FileNotFoundError, ValueError):
        data = None
    if data:
        flaky = [t for t in data.get("tests", []) if t.get("is_flaky")]
        lines += [
            "## Evidence: error messages per flaky test",
            "",
            f"_Report generated at {data['generated_at'][:19].replace('T', ' ')} UTC "
            f"(threshold {data['threshold']:g})._",
            "",
        ]
        if not any(t.get("error_messages") for t in flaky):
            lines.append("No error messages were recorded in this report.")
        else:
            lines += ["| Test | Score | Error messages |", "|---|---:|---|"]
            for t in flaky:
                msgs = sorted(set(t.get("error_messages") or []))
                cell = "<br>".join(m.replace("|", "\\|").replace("\n", " ") for m in msgs) or "_none recorded_"
                name = t["name"].replace("|", "\\|")
                lines.append(f"| `{name}` | {t['score']:.0%} | {cell} |")
        lines.append("")

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    path = ANALYSIS_DIR / f"flaky-analysis-{now.strftime('%Y%m%dT%H%M%SZ')}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    raise RuntimeError("GOOGLE_API_KEY is not set. Add it to the .env file.")

model = GeminiModel(
    client_args={"api_key": api_key},
    model_id="gemini-2.5-flash",
)
agent = Agent(
    model=model,
    tools=[fetch_json_report, export_analysis],
    name="Flaky Test Analysis Agent",
    description="This agent analyzes flaky test reports and provides insights on flaky tests, their scores, trends, and it analyzes the error messages to provide insights on the root causes of flakiness. And when it is asked to summarize the flaky test report, it will use the fetch_json_report tool to retrieve the report data and then provide a summary of how many tests are flaky and which are the worst and the possible root causes based on the error messages.",
    system_prompt="You are a helpful assistant that analyzes flaky test reports. Use the fetch_json_report tool to retrieve report data when needed. Always read the error_messages of each flaky test and infer the possible root causes (timeouts, race conditions, network/gateway instability, shared state, etc.), saying which tests each cause affects and how confident you are.After you finish analysing, call export_analysis once with summary, root_causes and recommendations to save the Markdown report, then tell the user the file path.",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze flaky test reports with an AI agent.")
    parser.add_argument("period", nargs="?", default="last_24_hours", choices=list(PERIODS),
                        help="period of reports to analyze (default: %(default)s)")
    args = parser.parse_args()
    label = args.period.replace("_", " ")
    agent(f"Summarize the flaky test reports from the {label} (period={args.period}): "
          "how many tests are flaky and which are the worst? After finishing, analyze the error messages to infer the possible root causes of flakiness and give recommendations to fix them. And create the report file with export_analysis tool, then tell me the path of the Markdown file that was written.")


if __name__ == "__main__":
    main()
