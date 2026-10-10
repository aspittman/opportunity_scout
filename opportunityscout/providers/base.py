"""Small provider contract and polite bounded HTTP retrieval."""
import time
from abc import ABC, abstractmethod
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = 'OpportunityScout/1.0 (local personal research)'


class PublicClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        retries = Retry(total=2, backoff_factor=1, status_forcelist=[502, 503, 504], allowed_methods=['GET'])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.last_request = 0

    def _get(self, url):
        time.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        response = self.session.get(url, timeout=(5, 25), allow_redirects=False)
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise ValueError('Unexpected redirect; update and verify the provider URL before retrieving.')
        return response

    def get(self, url, check_robots=True):
        if check_robots:
            origin = urlsplit(url)
            robots_url = f'{origin.scheme}://{origin.netloc}/robots.txt'
            try:
                response = self._get(robots_url)
            except requests.HTTPError as exc:
                # A missing robots file permits access; auth/rate/server failures do not.
                if exc.response is not None and exc.response.status_code == 404:
                    return self._get(url)
                raise
            parser = RobotFileParser(robots_url)
            parser.parse(response.text.splitlines())
            if not parser.can_fetch(USER_AGENT, url):
                raise ValueError('robots.txt disallows retrieval.')
            delay = parser.crawl_delay(USER_AGENT) or 1
            if delay > 60:
                raise ValueError('Source requires a crawl delay over 60 seconds; adapter disabled for this run.')
            time.sleep(max(0, delay - (time.monotonic() - self.last_request)))
        return self._get(url)


class Provider(ABC):
    name: str
    kind: str
    min_interval_hours = 6

    @abstractmethod
    def fetch(self):
        """Return raw records. Failed or malformed feeds must raise."""

    @abstractmethod
    def normalize(self, raw):
        """Return a validated-shape dictionary, never inferred pay or dates."""

    def accepts(self, record, settings):
        return True
