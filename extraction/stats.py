from github_client import GithubClient

def get_commit_activity(client, owner, repo):
    endpoint = f"/repos/{owner}/{repo}/stats/commit_activity"

    data = client.get(endpoint)

    commit_activity_data = []

    for week in data:
        commit_activity_data.append({
            "week": week.get('week'),
            "total_commits": week.get('total'),
            "sunday_commits": week.get('days')[0],
            "monday_commits": week.get('days')[1],
            "tuesday_commits": week.get('days')[2],
            "wednesday_commits": week.get('days')[3],
            "thursday_commits": week.get('days')[4],
            "friday_commits": week.get('days')[5],
            "saturday_commits": week.get('days')[6]
        })
    
    return commit_activity_data

def get_contributors_stats(client, owner, repo):
    endpoint = f"/repos/{owner}/{repo}/stats/contributors"

    data = client.get(endpoint)

    contributors = []

    for contributor in data:
        contributors.append({
            "author_login": contributor.get("author", {}).get("login"),
            "total_commits": contributor.get("total")
        })
    
    return contributors_stats_data


client = GithubClient()

commit_activity_data = get_stats(
    client,
    'torvalds',
    'linux'
)

contributors_stats_data = get_contributors_stats(
    client,
    'torvalds',
    'linux'
)

print(commit_activity_data)

print(contributors_stats_data)