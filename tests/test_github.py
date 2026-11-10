import io
import json
import zipfile

import pytest

from flaky_detector import github
from flaky_detector.github import GitHubError, fetch_junit_results, get_token, load_env

from .conftest import junit


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


# -- .env / token ----------------------------------------------------------

def test_load_env_parses_values(tmp_path, monkeypatch):
    for k in ("A", "B", "C", "D"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\n\nA=1\nexport B = two \nC=\"quoted value\"\nD='x'\nbad line\n")
    load_env(env)
    import os
    assert (os.environ["A"], os.environ["B"], os.environ["C"], os.environ["D"]) == ("1", "two", "quoted value", "x")


def test_load_env_does_not_override_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("A", "real")
    (tmp_path / ".env").write_text("A=file\n")
    load_env(tmp_path / ".env")
    import os
    assert os.environ["A"] == "real"


def test_load_env_missing_file_is_fine(tmp_path):
    load_env(tmp_path / "nope")


def test_get_token_from_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", " tok ")
    assert get_token() == "tok"


def test_get_token_missing_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github, "load_env", lambda *_: None)  # ignore the real .env
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        get_token()


# -- fetching --------------------------------------------------------------

class FakeClient:
    def __init__(self, runs, artifacts, zips):
        self.runs, self.artifacts, self.zips = runs, artifacts, zips

    def list_runs(self, repo, last_runs):
        return self.runs[:last_runs]

    def list_artifacts(self, repo, run_id):
        return self.artifacts.get(run_id, [])

    def download_artifact(self, repo, artifact_id):
        data = self.zips[artifact_id]
        if isinstance(data, Exception):
            raise data
        return data


def patch_client(monkeypatch, client):
    monkeypatch.setattr(github, "GitHubClient", lambda token: client)


def test_fetch_uses_run_metadata_when_xml_lacks_it(monkeypatch):
    xml = junit('<testcase classname="m" name="t"/>', sha=None, run_id=None)
    client = FakeClient(
        runs=[{"id": 11, "head_sha": "sha11"}],
        artifacts={11: [{"id": 1, "name": "results"}]},
        zips={1: make_zip({"out/junit.xml": xml, "out/readme.txt": "ignore me"})},
    )
    patch_client(monkeypatch, client)
    [r] = fetch_junit_results("o/r", token="t")
    assert (r.name, r.commit_sha, r.run_id) == ("m::t", "sha11", "11")
    assert r.source == "o/r#11/results/out/junit.xml"


def test_fetch_prefers_xml_properties(monkeypatch):
    xml = junit('<testcase name="t"/>', sha="from-xml", run_id="xml-run")
    patch_client(monkeypatch, FakeClient(
        [{"id": 1, "head_sha": "gh"}], {1: [{"id": 5, "name": "a"}]}, {5: make_zip({"j.xml": xml})}))
    [r] = fetch_junit_results("o/r", token="t")
    assert (r.commit_sha, r.run_id) == ("from-xml", "xml-run")


def test_fetch_warns_and_continues_on_bad_data(monkeypatch):
    good = junit('<testcase name="ok"/>')
    patch_client(monkeypatch, FakeClient(
        [{"id": 1, "head_sha": "s"}],
        {1: [{"id": 1, "name": "badzip"}, {"id": 2, "name": "api"}, {"id": 3, "name": "mixed"}]},
        {1: b"not a zip", 2: GitHubError("boom"),
         3: make_zip({"empty.xml": "", "good.xml": good})},
    ))
    warnings = []
    results = fetch_junit_results("o/r", token="t", warn=warnings.append)
    assert [r.name for r in results] == ["ok"]
    assert len(warnings) == 3


def test_fetch_respects_last_runs(monkeypatch):
    xml = junit('<testcase name="t"/>')
    runs = [{"id": i, "head_sha": "s"} for i in range(1, 6)]
    arts = {i: [{"id": i, "name": "a"}] for i in range(1, 6)}
    zips = {i: make_zip({"j.xml": xml}) for i in range(1, 6)}
    patch_client(monkeypatch, FakeClient(runs, arts, zips))
    assert len(fetch_junit_results("o/r", last_runs=2, token="t")) == 2


@pytest.mark.parametrize("repo", ["foo", "a/b/c", "", "a b/c", "/x"])
def test_invalid_repo_names(repo):
    with pytest.raises(GitHubError, match="invalid repo"):
        fetch_junit_results(repo, token="t")


# -- HTTP client -----------------------------------------------------------

def test_client_filters_expired_artifacts_and_paginates(monkeypatch):
    client = github.GitHubClient("tok")
    pages = {
        1: {"workflow_runs": [{"id": i} for i in range(100)]},
        2: {"workflow_runs": [{"id": 100 + i} for i in range(20)]},
    }
    calls = []

    def fake_json(path, **params):
        calls.append(params)
        if "artifacts" in path:
            return {"artifacts": [{"id": 1, "expired": True}, {"id": 2, "expired": False}]}
        return pages[params["page"]]

    monkeypatch.setattr(client, "_json", fake_json)
    assert len(client.list_runs("o/r", 120)) == 120
    assert [c["page"] for c in calls] == [1, 2]
    assert [a["id"] for a in client.list_artifacts("o/r", 1)] == [2]


def test_download_redirect_does_not_leak_token(monkeypatch):
    import urllib.error
    from email.message import Message

    client = github.GitHubClient("secret-token")
    seen = []

    class FakeOpener:
        def open(self, req):
            seen.append((req.full_url, req.get_header("Authorization")))
            if len(seen) == 1:
                h = Message()
                h["Location"] = "https://storage.example/blob"
                raise urllib.error.HTTPError(req.full_url, 302, "Found", h, None)

            class R:
                def __enter__(s): return s
                def __exit__(s, *a): pass
                def read(s): return b"zipdata"

            return R()

    client._opener = FakeOpener()
    assert client.download_artifact("o/r", 9) == b"zipdata"
    assert seen[0][1] == "Bearer secret-token"
    assert seen[1] == ("https://storage.example/blob", None)


def test_http_error_message_has_hint_and_no_token(monkeypatch):
    import urllib.error
    from email.message import Message

    client = github.GitHubClient("secret-token")

    class FakeOpener:
        def open(self, req):
            raise urllib.error.HTTPError(req.full_url, 401, "x", Message(),
                                         io.BytesIO(json.dumps({"message": "Bad credentials"}).encode()))

    client._opener = FakeOpener()
    with pytest.raises(GitHubError) as exc:
        client._request("https://api.github.com/repos/o/r/actions/runs?per_page=1")
    assert "401" in str(exc.value) and "Bad credentials" in str(exc.value)
    assert "secret-token" not in str(exc.value)
