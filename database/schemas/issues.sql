CREATE TABLE IF NOT EXISTS issues (
    id BIGINT PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id),
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    user_login TEXT,
    state TEXT,
    comments INTEGER,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ
);