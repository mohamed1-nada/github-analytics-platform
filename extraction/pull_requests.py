from github_client import GithubClient


def get_pull_requests(client, owner, repo):

    endpoint = f"/repos/{owner}/{repo}/pulls"

    prs_generator = client.get_with_pagination(endpoint)

    pull_requests = []

    for pr in prs_generator:

        pull_requests.append({
            "id": pr.get("id"),
            "number": pr.get("number"),
            "title": pr.get("title"),

            "user_login": pr.get("user", {}).get("login"),

            "state": pr.get("state"),

            "created_at": pr.get("created_at"),
            "updated_at": pr.get("updated_at"),
            "closed_at": pr.get("closed_at"),
            "merged_at": pr.get("merged_at"),

            "draft": pr.get("draft"),

            "merge_commit_sha": pr.get("merge_commit_sha"),
        })

    return pull_requests


client = GithubClient()

pull_requests_data = get_pull_requests(
    client,
    "facebook",
    "react"
)

print(len(pull_requests_data))
print(pull_requests_data[0])