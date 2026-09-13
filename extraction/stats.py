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
    
    contributor_info = data.get("author") or {}

    for contributor in data:
        yield {
            "author_login": contributor_info.get("login"),
            "total_commits": contributor.get("total")
        }
    
