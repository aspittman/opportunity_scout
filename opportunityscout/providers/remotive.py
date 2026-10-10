import re
from bs4 import BeautifulSoup
from .base import Provider, PublicClient


class RemotiveProvider(Provider):
    name = 'remotive'
    kind = 'income'
    endpoint = 'https://remotive.com/api/remote-jobs'

    def __init__(self, client=None):
        self.client = client or PublicClient()

    def fetch(self):
        # Documented API permission is authoritative; robots pertains to page crawling.
        payload = self.client.get(self.endpoint, check_robots=False).json()
        if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
            raise ValueError('Remotive returned an invalid jobs payload.')
        return payload['jobs']

    def normalize(self, raw):
        title = raw['title']
        source_id = str(raw['id'])
        url = raw['url']
        if not source_id or not title or not url.startswith('https://remotive.com/'):
            raise ValueError('Remotive record is missing required identity or attribution.')
        return dict(kind='income', title=title, organization=raw.get('company_name', ''),
                    category=raw.get('category', ''), location=raw.get('candidate_required_location', ''),
                    remote=True, url=url, description=BeautifulSoup(raw.get('description', ''), 'html.parser').get_text(' ', strip=True),
                    compensation_text=raw.get('salary') or 'Unknown', compensation_type='unknown',
                    arrangement=raw.get('job_type', ''), source_id=source_id,
                    employment_value='Remote job listing; eligibility and requirements need review.')

    def accepts(self, record, settings):
        if not settings['remote_preference']:
            return False
        location = record['location'].lower()
        # Conservative: US/worldwide eligibility must be explicit; no EU-only or unknown regions.
        return bool(re.search(r'\b(usa|us|united states|worldwide|anywhere|global)\b', location))
