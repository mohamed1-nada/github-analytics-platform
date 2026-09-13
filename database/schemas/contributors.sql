CREATE TABLE IF NOT EXISTS contributors (
    repository_id BIGINT NOT NULL REFERENCES repositories(id),
    author_login TEXT NOT NULL,
    total_commits INTEGER NOT NULL,

    PRIMARY KEY (repository_id, author_login)
);
