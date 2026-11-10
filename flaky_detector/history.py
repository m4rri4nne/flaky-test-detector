"""SQLite history of analysis snapshots, used to track flakiness over time."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .scoring import FlakinessRanker, TestScore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at       TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT '',
    threshold    REAL NOT NULL,
    min_commits  INTEGER NOT NULL,
    tests_total  INTEGER NOT NULL,
    flaky_count  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_tests (
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    commits       INTEGER NOT NULL,
    flaky_commits INTEGER NOT NULL,
    score         REAL NOT NULL,
    is_flaky      INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, name)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_tests_name ON snapshot_tests(name);
"""


@dataclass(frozen=True)
class Snapshot:
    id: int
    run_at: str
    source: str
    threshold: float
    min_commits: int
    tests_total: int
    flaky_count: int

    @property
    def flaky_rate(self) -> float:
        return self.flaky_count / self.tests_total if self.tests_total else 0.0


@dataclass(frozen=True)
class SnapshotDiff:
    """Change in the set of flaky tests between two snapshots."""

    new: tuple[str, ...]  # flaky now, not flaky before
    fixed: tuple[str, ...]  # flaky before, not flaky now


class HistoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def save(
        self,
        scores: Iterable[TestScore],
        ranker: FlakinessRanker,
        source: str = "",
        run_at: datetime | None = None,
    ) -> Snapshot:
        """Store one snapshot: every test with enough data, flaky or not."""
        eligible = ranker.rank(scores)
        flaky_names = {s.name for s in ranker.flaky(eligible)}
        when = (run_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO snapshots (run_at, source, threshold, min_commits,"
                " tests_total, flaky_count) VALUES (?, ?, ?, ?, ?, ?)",
                (when.isoformat(timespec="seconds"), source, ranker.threshold,
                 ranker.min_commits, len(eligible), len(flaky_names)),
            )
            snapshot_id = cur.lastrowid
            self._conn.executemany(
                "INSERT INTO snapshot_tests VALUES (?, ?, ?, ?, ?, ?)",
                [(snapshot_id, s.name, s.commits, s.flaky_commits, s.score,
                  int(s.name in flaky_names)) for s in eligible],
            )
        return self.get(snapshot_id)

    def get(self, snapshot_id: int) -> Snapshot:
        row = self._conn.execute("SELECT * FROM snapshots WHERE id = ?",
                                 (snapshot_id,)).fetchone()
        return Snapshot(**dict(row))

    def snapshots(self, source: str | None = None) -> list[Snapshot]:
        """All snapshots, oldest first; optionally only those of one source."""
        query, params = "SELECT * FROM snapshots", ()
        if source is not None:
            query, params = query + " WHERE source = ?", (source,)
        rows = self._conn.execute(query + " ORDER BY run_at, id", params).fetchall()
        return [Snapshot(**dict(r)) for r in rows]

    def flaky_names(self, snapshot_id: int) -> set[str]:
        rows = self._conn.execute(
            "SELECT name FROM snapshot_tests WHERE snapshot_id = ? AND is_flaky = 1",
            (snapshot_id,)).fetchall()
        return {r["name"] for r in rows}

    def diff(self, previous_id: int, current_id: int) -> SnapshotDiff:
        before, now = self.flaky_names(previous_id), self.flaky_names(current_id)
        return SnapshotDiff(new=tuple(sorted(now - before)),
                            fixed=tuple(sorted(before - now)))

    def test_history(self, snapshot_ids: list[int], names: Iterable[str]
                     ) -> dict[str, list[float | None]]:
        """Score of each test per snapshot (None where the test had too little data)."""
        history: dict[str, dict[int, float]] = {n: {} for n in names}
        if not history or not snapshot_ids:
            return {n: [] for n in history}
        marks = ",".join("?" * len(snapshot_ids))
        rows = self._conn.execute(
            f"SELECT snapshot_id, name, score FROM snapshot_tests"
            f" WHERE snapshot_id IN ({marks})", snapshot_ids).fetchall()
        for r in rows:
            if r["name"] in history:
                history[r["name"]][r["snapshot_id"]] = r["score"]
        return {n: [by_snap.get(i) for i in snapshot_ids] for n, by_snap in history.items()}
