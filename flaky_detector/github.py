"""Fetch JUnit XML test results from GitHub Actions artifacts.

Every workflow run is listed, its artifacts are downloaded, and each ``.xml``
file inside them is parsed as JUnit. The commit SHA and run id come from the
GitHub run itself unless the XML already carries them as properties.
"""

from __future__ import annotations

import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from .parsers import JUnitParseError, JUnitParser, TestResult

API = "https://api.github.com"
TOKEN_VAR = "GITHUB_TOKEN"


class GitHubError(RuntimeError):
    """Raised when the GitHub API call fails or the token is missing."""


def load_env(path: str | Path = ".env") -> None:
    """Load ``KEY=VALUE`` lines from ``path`` into ``os.environ`` (existing vars win)."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def get_token() -> str:
    """Token from the environment, falling back to ``.env`` (cwd, then project root)."""
    for env_file in (Path(".env"), Path(__file__).resolve().parent.parent / ".env"):
        load_env(env_file)
    token = os.environ.get(TOKEN_VAR, "").strip()
    if not token:
        raise GitHubError(f"{TOKEN_VAR} not found in the environment or in .env")
    return token


def _ssl_context() -> ssl.SSLContext:
    """Default context, falling back to certifi / the macOS bundle.

    python.org builds of Python on macOS ship without CA certificates, which
    makes every HTTPS call fail with CERTIFICATE_VERIFY_FAILED.
    """
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca"):
        return ctx
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for bundle in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(bundle):
            return ssl.create_default_context(cafile=bundle)
    return ctx


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


class GitHubClient:
    def __init__(self, token: str) -> None:
        self._token = token
        self._opener = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPSHandler(context=_ssl_context())
        )

    def _request(self, url: str, auth: bool = True) -> bytes:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "flaky-test-detector",
        }
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            with self._opener.open(urllib.request.Request(url, headers=headers)) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                # Artifact downloads redirect to signed storage URLs, which must
                # not receive the GitHub token.
                return self._request(exc.headers["Location"], auth=False)
            detail = ""
            try:
                detail = json.loads(exc.read()).get("message", "")
            except Exception:
                pass
            hint = " (check that the token is valid and has access)" if exc.code in (401, 403, 404) else ""
            raise GitHubError(f"GitHub API {exc.code} for {url.split('?')[0]}: {detail}{hint}") from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"could not reach GitHub: {exc.reason}") from exc

    def _json(self, path: str, **params) -> dict:
        query = urllib.parse.urlencode(params)
        return json.loads(self._request(f"{API}{path}?{query}"))

    def list_runs(self, repo: str, last_runs: int) -> list[dict]:
        runs: list[dict] = []
        page = 1
        while len(runs) < last_runs:
            data = self._json(
                f"/repos/{repo}/actions/runs",
                per_page=min(100, last_runs), page=page, status="completed",
            )
            batch = data.get("workflow_runs", [])
            runs.extend(batch)
            if len(batch) < min(100, last_runs):
                break
            page += 1
        return runs[:last_runs]

    def list_artifacts(self, repo: str, run_id: int) -> list[dict]:
        data = self._json(f"/repos/{repo}/actions/runs/{run_id}/artifacts", per_page=100)
        return [a for a in data.get("artifacts", []) if not a.get("expired")]

    def download_artifact(self, repo: str, artifact_id: int) -> bytes:
        return self._request(f"{API}/repos/{repo}/actions/artifacts/{artifact_id}/zip")


def fetch_junit_results(
    repo: str,
    last_runs: int = 30,
    token: str | None = None,
    parser: JUnitParser | None = None,
    warn=lambda msg: print(f"warning: {msg}", file=sys.stderr),
) -> list[TestResult]:
    """Parse every JUnit XML found in the artifacts of the last ``last_runs`` runs."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise GitHubError(f"invalid repo {repo!r}, expected 'owner/name'")
    client = GitHubClient(token or get_token())
    parser = parser or JUnitParser()

    results: list[TestResult] = []
    for run in client.list_runs(repo, last_runs):
        run_id, sha = str(run["id"]), run.get("head_sha")
        for artifact in client.list_artifacts(repo, run["id"]):
            try:
                archive = zipfile.ZipFile(io.BytesIO(client.download_artifact(repo, artifact["id"])))
            except (GitHubError, zipfile.BadZipFile) as exc:
                warn(f"run {run_id}, artifact {artifact['name']}: {exc}")
                continue
            for member in archive.namelist():
                if not member.lower().endswith(".xml"):
                    continue
                source = f"{repo}#{run_id}/{artifact['name']}/{member}"
                try:
                    results.extend(
                        parser.parse_string(
                            archive.read(member), source=source,
                            default_commit_sha=sha, default_run_id=run_id,
                        )
                    )
                except JUnitParseError as exc:
                    warn(str(exc))
    return results
