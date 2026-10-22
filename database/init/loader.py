import logging

from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)


def load_in_batches(data_generator, batch_size, insert_func) -> int:
    """Consume ``data_generator`` in batches; return the number of rows loaded."""
    batch = []
    total_loaded = 0
    for data in data_generator:
        batch.append(data)

        if len(batch) == batch_size:
            insert_func(batch)
            total_loaded += len(batch)
            logger.info("Loaded batch: %d rows | Total loaded: %d", len(batch), total_loaded)
            batch.clear()

    if batch:
        insert_func(batch)
        total_loaded += len(batch)
        logger.info("Loaded final batch: %d rows | Total loaded: %d", len(batch), total_loaded)

    return total_loaded


def attach_repository_id(data_generator, repository_id):
    for row in data_generator:
        row["repository_id"] = repository_id
        yield row


def dedupe_rows(batch, *keys):
    """Drop rows sharing a conflict key within one batch (last write wins).

    GitHub's list endpoints are paginated by ``updated_at desc``, so an item
    that changes between two page requests can be returned twice. A single
    ``INSERT ... ON CONFLICT DO UPDATE`` rejects that with "cannot affect row a
    second time", so keep only the last occurrence of each key.
    """
    latest = {}
    for row in batch:
        latest[tuple(row[key] for key in keys)] = row
    return list(latest.values())


def insert_repositories(conn, repo):

    cursor = conn.cursor()

    sql = """
        INSERT INTO repositories(
            id,
            name,
            full_name,
            owner_login,
            description,
            language,
            created_at,
            updated_at,
            pushed_at,
            stargazers_count,
            forks_count,
            watchers_count,
            open_issues,
            default_branch,
            size,
            archived,
            topics
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            full_name = EXCLUDED.full_name,
            owner_login = EXCLUDED.owner_login,
            description = EXCLUDED.description,
            language = EXCLUDED.language,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at,
            pushed_at = EXCLUDED.pushed_at,
            stargazers_count = EXCLUDED.stargazers_count,
            forks_count = EXCLUDED.forks_count,
            watchers_count = EXCLUDED.watchers_count,
            open_issues = EXCLUDED.open_issues,
            default_branch = EXCLUDED.default_branch,
            size = EXCLUDED.size,
            archived = EXCLUDED.archived,
            topics = EXCLUDED.topics
    """

    values = (
        repo["id"],
        repo["name"],
        repo["full_name"],
        repo["owner_login"],
        repo["description"],
        repo["language"],
        repo["created_at"],
        repo["updated_at"],
        repo["pushed_at"],
        repo["stargazers_count"],
        repo["forks_count"],
        repo["watchers_count"],
        repo["open_issues"],
        repo["default_branch"],
        repo["size"],
        repo["archived"],
        repo["topics"],
    )

    try:
        cursor.execute(sql, values)
    finally:
        cursor.close()


def insert_commits(conn, batch):

    cursor = conn.cursor()

    sql = """
        INSERT INTO commits(
            repository_id,
            sha,
            author_login,
            author_name,
            committer_login,
            commit_author_date,
            commit_committer_date,
            commit_message
        )
        VALUES %s
        ON CONFLICT (repository_id, sha) DO NOTHING
    """

    values = [
        (
            row["repository_id"],
            row["sha"],
            row["author_login"],
            row["author_name"],
            row["committer_login"],
            row["commit_author_date"],
            row["commit_committer_date"],
            row["commit_message"],
        )
        for row in batch
    ]

    try:
        execute_values(cursor, sql, values)
    finally:
        cursor.close()


def insert_issues(conn, batch):
    batch = dedupe_rows(batch, "id")
    cursor = conn.cursor()
    sql = """
        INSERT INTO issues(
            repository_id,
            id,
            number,
            title,
            user_login,
            state,
            comments,
            created_at,
            updated_at,
            closed_at
        )
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            number = EXCLUDED.number,
            title = EXCLUDED.title,
            user_login = EXCLUDED.user_login,
            state = EXCLUDED.state,
            comments = EXCLUDED.comments,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at,
            closed_at = EXCLUDED.closed_at
    """
    values = [
        (
            row["repository_id"],
            row["id"],
            row["number"],
            row["title"],
            row["user_login"],
            row["state"],
            row["comments"],
            row["created_at"],
            row["updated_at"],
            row["closed_at"],
        )
        for row in batch
    ]
    try:
        execute_values(cursor, sql, values)
    finally:
        cursor.close()


def insert_pull_requests(conn, batch):
    batch = dedupe_rows(batch, "id")
    cursor = conn.cursor()
    sql = """
        INSERT INTO pull_requests(
            repository_id,
            id,
            number,
            title,
            user_login,
            state,
            created_at,
            updated_at,
            closed_at,
            merged_at,
            draft,
            merge_commit_sha
        )
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            number = EXCLUDED.number,
            title = EXCLUDED.title,
            user_login = EXCLUDED.user_login,
            state = EXCLUDED.state,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at,
            closed_at = EXCLUDED.closed_at,
            merged_at = EXCLUDED.merged_at,
            draft = EXCLUDED.draft,
            merge_commit_sha = EXCLUDED.merge_commit_sha
    """
    values = [
        (
            row["repository_id"],
            row["id"],
            row["number"],
            row["title"],
            row["user_login"],
            row["state"],
            row["created_at"],
            row["updated_at"],
            row["closed_at"],
            row["merged_at"],
            row["draft"],
            row["merge_commit_sha"],
        )
        for row in batch
    ]
    try:
        execute_values(cursor, sql, values)
    finally:
        cursor.close()


def insert_commit_activity(conn, batch):
    batch = dedupe_rows(batch, "repository_id", "week")
    cursor = conn.cursor()
    sql = """
        INSERT INTO commit_activity(
            repository_id,
            week,
            total_commits,
            sunday_commits,
            monday_commits,
            tuesday_commits,
            wednesday_commits,
            thursday_commits,
            friday_commits,
            saturday_commits
        )
        VALUES %s
        ON CONFLICT (repository_id, week) DO UPDATE SET
            total_commits = EXCLUDED.total_commits,
            sunday_commits = EXCLUDED.sunday_commits,
            monday_commits = EXCLUDED.monday_commits,
            tuesday_commits = EXCLUDED.tuesday_commits,
            wednesday_commits = EXCLUDED.wednesday_commits,
            thursday_commits = EXCLUDED.thursday_commits,
            friday_commits = EXCLUDED.friday_commits,
            saturday_commits = EXCLUDED.saturday_commits
    """
    values = [
        (
            row["repository_id"],
            row["week"],
            row["total_commits"],
            row["sunday_commits"],
            row["monday_commits"],
            row["tuesday_commits"],
            row["wednesday_commits"],
            row["thursday_commits"],
            row["friday_commits"],
            row["saturday_commits"],
        )
        for row in batch
    ]
    try:
        execute_values(cursor, sql, values)
    finally:
        cursor.close()


def insert_contributors(conn, batch):
    batch = dedupe_rows(batch, "repository_id", "author_login")
    cursor = conn.cursor()
    sql = """
        INSERT INTO contributors(
            repository_id,
            author_login,
            total_commits
        )
        VALUES %s
        ON CONFLICT (repository_id, author_login) DO UPDATE SET
            total_commits = EXCLUDED.total_commits
    """
    values = [
        (
            row["repository_id"],
            row["author_login"],
            row["total_commits"],
        )
        for row in batch
    ]
    try:
        execute_values(cursor, sql, values)
    finally:
        cursor.close()
