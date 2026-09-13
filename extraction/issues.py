def get_issues(client, owner, repo , since = None , until = None):

    endpoint = f"/repos/{owner}/{repo}/issues"
    params = {}
    if since:
        params['since'] = since
    if until:
        params['until'] = until
    issues_generator = client.get_with_pagination(endpoint , params)
    
    for issue in issues_generator:
        if "pull_request" in issue:
            continue
        yield {
            "id": issue.get("id"),
            "number": issue.get("number"),
            "title": issue.get("title"),

            "user_login": issue.get(("user") or {}).get("login"),

            "state": issue.get("state"),

            "comments": issue.get("comments"),

            "created_at": issue.get("created_at"),
            "updated_at": issue.get("updated_at"),
            "closed_at": issue.get("closed_at"),
        }

 
