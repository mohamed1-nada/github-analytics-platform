CREATE TABLE IF NOT EXISTS commits (
    repository_id BIGINT NOT NULL REFERENCES repositories(id),
    sha TEXT NOT NULL,

    author_login TEXT,
    author_name TEXT,
    committer_login TEXT,

    commit_author_date TIMESTAMPTZ,
    commit_committer_date TIMESTAMPTZ,

    commit_message TEXT,

    PRIMARY KEY (repository_id, sha)
);
