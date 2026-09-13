from extraction.github_client import GithubClient
from extraction.repositories import get_repo
from extraction.commits import get_commits
from extraction.pull_requests import get_pull_requests
from extraction.issues import get_issues
from extraction.stats import get_commit_activity , get_contributors_stats

from database.init.db import create_connection
from database.init.loader import (
    load_in_batches,
    attach_repository_id,
    insert_repositories,
    insert_commits,
    insert_issues,
    insert_pull_requests,
    insert_commit_activity,
    insert_contributors
)
import logging
from datetime import timezone, timedelta , datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def run_step(step_name ,conn , extract_func , load_func):
    """
        Run one pipeline step independently.
        if the step fails, log the error and continue
        with the remaining pipeline steps
    """
    try:
        logger.info(f"Starting {step_name} extraction")         
        data = extract_func()
        
        if data:
            logger.info(f" Starting {step_name} loading")
            load_func(data)
            # commit everything after each step
            conn.commit()
            logger.info(f"{step_name} completed successfully")
        else:
            logger.info(f"No data to load for {step_name}")
    except Exception as e:
        # rollback everything if any step fails
        conn.rollback()
        logger.error(f'{step_name} failed: {str(e)}' , exc_info=True)
        return "Failed"
    
    return "Success"


def run_pipeline(owner , repo_name , BATCH_SIZE , since , until):
    
    logger.info(f'Starting pipeline for {owner}/{repo_name} from {since} to {until}')

    client = GithubClient()
    # 1- extract repositories

    logger.info("Extracting repository")
    try:
        repo = get_repo(client, owner, repo_name)
        
        logger.info(f'Repository extracted successfully: {repo["full_name"]}')
    
    except Exception as e:
        
        logger.error(f'Repository extraction failed: {str(e)}' , exc_info=True)
        
        return

    # 2- DATABASE connection
    conn = create_connection()
    try:
        # load repository
        try:
            logger.info("Loading repository")

            insert_repositories(conn, repo)

            logger.info(f'Repository loaded successfully: {repo["full_name"]}')
        except Exception as e:
            logger.error(f'Repository loading failed: {str(e)}' , exc_info=True)
            
            conn.rollback()
            return
    
        # pipeline results
        results = {}

        # 3- extract commits
        results["commits"] = run_step(
            "commits" ,
            conn,
            lambda: get_commits(client, owner, repo_name , since = since , until = until) ,
            lambda data: load_in_batches(
                attach_repository_id(data, repo["id"]),
                BATCH_SIZE,
                lambda batch: insert_commits(conn, batch))
        )
        
        # repeat this pattern for other tables
        
        #  extract pull requests
        results["pull_requests"] = run_step(
            "pull_requests" ,
            conn,
            lambda: get_pull_requests(client, owner, repo_name , since = since , until = until) ,
            lambda data: load_in_batches(
                attach_repository_id(data, repo["id"]),
                BATCH_SIZE,
                lambda batch: insert_pull_requests(conn, batch))
        )   
        
        #  extract issues
        results["issues"] = run_step(
            "issues" ,
            conn,
            lambda: get_issues(client, owner, repo_name , since = since , until = until) ,
            lambda data: load_in_batches(
                attach_repository_id(data, repo["id"]),
                BATCH_SIZE,
                lambda batch: insert_issues(conn, batch))
        )
        
        #  extract commit activity
        results["commit_activity"] = run_step(
            "commit_activity" ,
            conn,
            lambda: get_commit_activity(client, owner, repo_name) ,
            lambda data: load_in_batches(
                attach_repository_id(data, repo["id"]),
                BATCH_SIZE,
                lambda batch: insert_commit_activity(conn, batch))
        )
 
        #  extract contributors
        results["contributors"] = run_step(
            "contributors" ,
            conn,
            lambda: get_contributors_stats(client, owner, repo_name) ,
            lambda data: load_in_batches(
                attach_repository_id(data, repo["id"]),
                BATCH_SIZE,
                lambda batch: insert_contributors(conn, batch))
        )
        # final summary
        logger.info("=" * 50)
        logger.info(f"PIPELINE SUMMARY")
        logger.info("=" * 50)

        for step, status in results.items():
            logger.info(f"{step:>20} {status}")

        logger.info("=" * 50)
        
    except Exception as e:
        conn.rollback()
        logger.error(f'Unexpected pipeline error: {str(e)}' , exc_info=True)
    finally:
        conn.close()
        logger.info("Database connection closed")

def main():

    BATCH_SIZE = 100
    until = datetime.now(timezone.utc)    
    since = until - timedelta(days=30)
    
    repos = [
        ("torvalds" , "linux"),
        ("facebook" , "react"),
        ("microsoft" , "vscode")
    ]
    
    for owner , repo_name in repos:
        run_pipeline(owner , repo_name , BATCH_SIZE , since , until)

if __name__ == "__main__":
    main()
