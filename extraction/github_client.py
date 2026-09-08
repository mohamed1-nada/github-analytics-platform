import os
import time
import logging
import requests

from dotenv import load_dotenv
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

class GithubClient:

    API_TOKEN = os.getenv("GITHUB_TOKEN")
    BASE_URL = os.getenv("BASE_URL")

    def __init__(self):

        self.session = requests.Session()

        self.session.headers.update({
            "Authorization": f"Bearer {self.API_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        })


    def _handle_rate_limit(self, response):
        
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_time = response.headers.get("X-RateLimit-Reset")

        if (remaining and int(remaining) == 0) or response.status_code == 429:

            if reset_time:
            
                sleep_time = max(int(reset_time) - int(time.time()) , 1) + 1
            
                logger.warning(f"Rate limit hit. Sleeping for {sleep_time} seconds")
            
                time.sleep(sleep_time)
            
                return True

        return False
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)),
        reraise=True
    )
    def _get(self, endpoint, params=None) -> requests.Response:

        url = f"{self.BASE_URL}{endpoint}"

        logger.info(f"GET {url}")

        while True:

            response = self.session.get(
                url,
                params=params,
                timeout=(10, 30)
            )
            
            # Rate limit
            if self._handle_rate_limit(response):
                continue
            
            # HTTP Errors
            response.raise_for_status()

            logger.info(f"Response: {response.status_code}")

            return response

    def get(self, endpoint, params=None):

        response = self._get(endpoint, params)

        return response.json()

    def get_with_pagination(self, endpoint, params=None):

        params = params.copy() if params else {}

        params.setdefault("page", 1)
        params.setdefault("per_page", 100)

        while True:

            response = self._get(endpoint, params)

            data = response.json()

            for item in data:
                yield item

            link_header = response.headers.get("Link", "")

            if 'rel="next"' not in link_header:
                break

            params["page"] += 1

    