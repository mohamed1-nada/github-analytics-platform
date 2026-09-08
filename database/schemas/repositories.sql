CREATE TABLE IF NOT EXISTS repositories (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL UNIQUE,
    owner_login TEXT,
    description TEXT,
    language TEXT,

    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    pushed_at TIMESTAMPTZ,

    stargazers_count INTEGER,
    forks_count INTEGER,
    watchers_count INTEGER,
    open_issues INTEGER,

    default_branch TEXT,
    size INTEGER,
    archived BOOLEAN,

    topics TEXT[]
);