def get_commit_activity(client, owner, repo):
    endpoint = f"/repos/{owner}/{repo}/stats/commit_activity"

    data = client.get(endpoint)

    for week in data:
        yield {
            "week": week.get('week'),
            "total_commits": week.get('total'),
            "sunday_commits": week.get('days')[0],
            "monday_commits": week.get('days')[1],
            "tuesday_commits": week.get('days')[2],
            "wednesday_commits": week.get('days')[3],
            "thursday_commits": week.get('days')[4],
            "friday_commits": week.get('days')[5],
            "saturday_commits": week.get('days')[6]
        }
    
def get_contributors_stats(client, owner, repo):
    endpoint = f"/repos/{owner}/{repo}/stats/contributors"
 
    data = client.get(endpoint)
    
    for contributor in data:
        author_info = contributor.get("author") or {}
        author_login = author_info.get("login")
        # skip None and deleted accounts
        if not author_login:
            continue
        yield {
            "author_login": author_login,
            "total_commits": contributor.get("total")
        }
    
