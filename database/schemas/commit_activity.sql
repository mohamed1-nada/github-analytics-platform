CREATE TABLE IF NOT EXISTS commit_activity (
    repository_id BIGINT NOT NULL REFERENCES repositories(id),
    week BIGINT NOT NULL,
    total_commits INTEGER NOT NULL,
    sunday_commits INTEGER NOT NULL,
    monday_commits INTEGER NOT NULL,
    tuesday_commits INTEGER NOT NULL,
    wednesday_commits INTEGER NOT NULL,
    thursday_commits INTEGER NOT NULL,
    friday_commits INTEGER NOT NULL,
    saturday_commits INTEGER NOT NULL,

    PRIMARY KEY (repository_id, week)
);
