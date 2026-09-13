def get_pull_requests(client, owner, repo , since = None , until = None):

    endpoint = f"/repos/{owner}/{repo}/pulls"
    params = {}
    if since:
        params['since'] = since
    if until:   
        params['until'] = until
        
    prs_generator = client.get_with_pagination(endpoint , params)
    
    for pr in prs_generator:

        yield {
            "id": pr.get("id"),
            "number": pr.get("number"),
            "title": pr.get("title"),

            "user_login": pr.get(("user") or {}).get("login"),

            "state": pr.get("state"),

            "created_at": pr.get("created_at"),
            "updated_at": pr.get("updated_at"),
            "closed_at": pr.get("closed_at"),
            "merged_at": pr.get("merged_at"),

            "draft": pr.get("draft"),

            "merge_commit_sha": pr.get("merge_commit_sha"),
        }

