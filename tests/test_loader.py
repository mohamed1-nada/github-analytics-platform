from database.init.loader import attach_repository_id, dedupe_rows, load_in_batches


def test_dedupe_rows_keeps_last_occurrence_per_key():
    rows = [
        {"id": 1, "state": "open"},
        {"id": 2, "state": "open"},
        {"id": 1, "state": "closed"},
    ]
    out = dedupe_rows(rows, "id")
    assert out == [{"id": 1, "state": "closed"}, {"id": 2, "state": "open"}]


def test_dedupe_rows_uses_composite_key():
    rows = [
        {"repository_id": 1, "author_login": "a", "total_commits": 1},
        {"repository_id": 1, "author_login": "a", "total_commits": 9},
        {"repository_id": 1, "author_login": "b", "total_commits": 1},
    ]
    out = dedupe_rows(rows, "repository_id", "author_login")
    assert out == [
        {"repository_id": 1, "author_login": "a", "total_commits": 9},
        {"repository_id": 1, "author_login": "b", "total_commits": 1},
    ]


def test_attach_repository_id():
    rows = ({"sha": s} for s in ["a", "b"])
    out = list(attach_repository_id(rows, 42))
    assert out == [{"sha": "a", "repository_id": 42}, {"sha": "b", "repository_id": 42}]


def test_load_in_batches():
    inserted = []
    loaded = load_in_batches(iter(range(7)), 3, lambda batch: inserted.append(list(batch)))
    assert inserted == [[0, 1, 2], [3, 4, 5], [6]]
    assert loaded == 7


def test_load_in_batches_with_no_rows():
    inserted = []
    assert load_in_batches(iter(()), 3, inserted.append) == 0
    assert inserted == []
