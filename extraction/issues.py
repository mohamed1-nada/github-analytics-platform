from github_client import GithubClient

def get_issues(client, owner, repo):

    endpoint = f"/repos/{owner}/{repo}/issues"

    issues_generator = client.get_with_pagination(endpoint)
    # this code now dengerous because allocates memory for all commits in memory this need to be changed to stream
    issues = []
    for issue in issues_generator:
        if "pull_request" in issue:
            continue
        issues.append({
            "id": issue.get("id"),
            "number": issue.get("number"),
            "title": issue.get("title"),

            "user_login": issue.get("user", {}).get("login"),

            "state": issue.get("state"),

            "comments": issue.get("comments"),

            "created_at": issue.get("created_at"),
            "updated_at": issue.get("updated_at"),
            "closed_at": issue.get("closed_at"),
        })
    return issues
client = GithubClient()

issues_data = get_issues(
    client,
    'torvalds',
    'linux'
)
