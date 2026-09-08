from github_client import GithubClient

def get_commits(client, owner, repo):

    endpoint = f"/repos/{owner}/{repo}/commits"

    commits_generator = client.get_with_pagination(endpoint)
     
    commits = []
    for commit in commits_generator:
        commits.append({
        'sha': commit.get('sha'),
        'author_login': commit.get('author', {}).get('login'),
        'author_name': commit.get('commit', {}).get('author', {}).get('name'),
        'committer_login': commit.get('committer', {}).get('login'),
        'commit_author_date': commit.get('commit', {}).get('author', {}).get('date'),
        'commit_committer_date': commit.get('commit', {}).get('committer', {}).get('date'),
        'commit_message': commit.get('commit', {}).get('message'),
        })
    return commits
client = GithubClient()

commits_data = get_commits(
    client,
    'torvalds',
    'linux'
)
