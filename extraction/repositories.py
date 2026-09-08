from github_client import GithubClient


def get_repo(client, owner, repo):

    endpoint = f"/repos/{owner}/{repo}"

    data = client.get(endpoint)

    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "full_name": data.get("full_name"),
        "owner_login": data.get("owner", {}).get("login"),
        "description": data.get("description"),
        "language": data.get("language"),

        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "pushed_at": data.get("pushed_at"),

        "stargazers_count": data.get("stargazers_count"),
        "forks_count": data.get("forks_count"),
        "watchers_count": data.get("watchers_count"),
        "open_issues": data.get("open_issues"),
        "default_branch": data.get("default_branch"),
        "size": data.get("size"),
        "archived": data.get("archived"),
        "topics": data.get("topics"),
    }

client = GithubClient()

repo = get_repo(
    client,
    'torvalds',
    'linux'
)
print(repo)