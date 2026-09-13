def get_commits(client, owner, repo , since = None , until = None):

    endpoint = f"/repos/{owner}/{repo}/commits"
    params = {}
    if since:
        params['since'] = since
    if until:
        params['until'] = until
        
    commits_generator = client.get_with_pagination(endpoint , params)

    for commit in commits_generator:

        commit_data = commit.get("commit") or {}
        author_data = commit_data.get("author") or {}
        committer_data = commit_data.get("committer") or {}

        yield {
            "sha": commit.get("sha"),

            "author_login": (commit.get("author") or {}).get("login"),
            "author_name": author_data.get("name"),

            "committer_login": (commit.get("committer") or {}).get("login"),

            "commit_author_date": author_data.get("date"),
            "commit_committer_date": committer_data.get("date"),

            "commit_message": commit_data.get("message"),
        }