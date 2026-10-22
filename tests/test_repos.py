from pathlib import Path

import requests
import yaml

from main import collect_repos
from repos import check_token, dedupe, load_repos_file, parse_repo


class _FakeResponse(requests.Response):
    def __init__(self, status_code: int):
        super().__init__()
        self.status_code = status_code


def test_check_token_rejects_expired_token():
    class FakeClient:
        def get(self, endpoint):
            raise requests.exceptions.HTTPError(response=_FakeResponse(401))

    try:
        check_token(FakeClient())
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "GITHUB_TOKEN" in str(e)


def test_parse_repo():
    assert parse_repo("torvalds/linux") == ("torvalds", "linux")


def test_dedupe_keeps_order():
    repos = [("a", "b"), ("c", "d"), ("a", "b")]
    assert dedupe(repos) == [("a", "b"), ("c", "d")]


def test_load_repos_file(tmp_path: Path):
    path = tmp_path / "repos.yaml"
    path.write_text(
        yaml.dump(
            {
                "repos": ["torvalds/linux", "facebook/react"],
                "topics": ["rust", {"name": "mlops", "top": 3}],
            }
        )
    )
    direct, topics = load_repos_file(path)
    assert direct == [("torvalds", "linux"), ("facebook", "react")]
    assert topics == [("rust", 10), ("mlops", 3)]


def test_load_repos_file_missing(tmp_path: Path):
    assert load_repos_file(tmp_path / "nope.yaml") == ([], [])


def test_collect_repos_no_topics(tmp_path: Path):
    path = tmp_path / "repos.yaml"
    path.write_text(yaml.dump({"repos": ["a/b", "c/d", "a/b"]}))

    class Args:
        repo = None
        repos_file = str(path)
        no_topics = True

    assert collect_repos(Args()) == [("a", "b"), ("c", "d")]
