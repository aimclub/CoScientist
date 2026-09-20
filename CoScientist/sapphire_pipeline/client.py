from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def openalex_id(value):
    """Return a canonical W-prefixed work ID from an OpenAlex ID or URL.

    Return None when the value is not a supported work identifier.
    """
    if not isinstance(value, str):
        return None
    value = value.strip().rstrip('/')
    if value.startswith(('http://openalex.org/', 'https://openalex.org/')):
        value = value.rsplit('/', 1)[-1]
    return value.upper() if re.fullmatch(r'W\d+', value, re.I) else None


def normalize_doi(value):
    """Strip known DOI prefixes and lowercase the identifier.

    Return None for non-string values or values without the expected DOI shape.
    """
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/', 'doi:'):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    return value if value.startswith('10.') and '/' in value else None


class SapphireClient:
    def __init__(self, url, page_size=100, timeout=60, max_pdf_bytes=100 * 1024 * 1024):
        """Create a reusable HTTP session with retries for transient GET failures.

        Args:
            url: Base Sapphire API URL.
            page_size: Number of publications requested per page.
            timeout: Connection and read timeout in seconds for each request.
            max_pdf_bytes: Maximum allowed size of a downloaded PDF in bytes.

        Raises:
            ValueError: If page_size, timeout, or max_pdf_bytes is not positive.
        """
        if page_size < 1 or timeout <= 0 or max_pdf_bytes < 1:
            raise ValueError('page_size, timeout and max_pdf_bytes must be positive')
        self.url = url.rstrip('/')
        self.page_size = page_size
        self.timeout = timeout
        self.max_pdf_bytes = max_pdf_bytes
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=['GET'])
        self.session.mount('http://', HTTPAdapter(max_retries=retry))
        self.session.mount('https://', HTTPAdapter(max_retries=retry))

    def close(self):
        """Close the HTTP session and release its pooled connections."""
        self.session.close()

    def get_json(self, path, **params):
        """GET an API path with query parameters and return its decoded JSON.

        HTTP, transport, and JSON decoding errors propagate to the caller.
        """
        with self.session.get(self.url + path, params=params, timeout=self.timeout) as response:
            response.raise_for_status()
            return response.json()

    def publications(self):
        """Yield publication dictionaries using limit/offset pagination.

        Stop at an empty page. Reject malformed responses and consecutive identical
        pages so an ignored offset does not cause an endless loop.
        """
        offset = 0
        previous = None
        while True:
            page = self.get_json('/publications', limit=self.page_size, offset=offset)
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise ValueError('/publications must return an array of objects')
            if not page:
                return
            if page == previous:
                raise RuntimeError('Sapphire returned the same page twice; offset may be ignored')
            yield from page
            offset += len(page)
            previous = page

    def work(self, identifier):
        """Fetch an OpenAlex work through Sapphire using its ID or OpenAlex URL.

        Raise ValueError for an invalid identifier, a non-object response, or a
        response whose supplied work ID differs from the requested ID.
        """
        identifier = openalex_id(identifier)
        if not identifier:
            raise ValueError('Invalid OpenAlex work ID')
        work = self.get_json(f'/crawler/openalex/works/{identifier}')
        if not isinstance(work, dict):
            raise ValueError('OpenAlex work response must be an object')
        if work.get('id') and openalex_id(work['id']) != identifier:
            raise ValueError('OpenAlex work ID does not match the requested publication')
        return work

    def download_pdf(self, url):
        """Download a candidate PDF into memory and return its bytes.

        Require an HTTP(S) URL without credentials, a successful HTTP response,
        a size within max_pdf_bytes, and a PDF signature in the first 1024 bytes.
        Raise ValueError for rejected input/content; HTTP errors propagate.
        The signature check does not validate the entire PDF document.
        """
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('PDF URL must be an HTTP(S) URL without credentials')
        with self.session.get(url, timeout=self.timeout, stream=True) as response:
            response.raise_for_status()
            if int(response.headers.get('Content-Length', 0)) > self.max_pdf_bytes:
                raise ValueError('PDF exceeds size limit')
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                data.extend(chunk)
                if len(data) > self.max_pdf_bytes:
                    raise ValueError('PDF exceeds size limit')
                if len(data) >= 1024 and b'%PDF-' not in data[:1024]:
                    raise ValueError('URL returned non-PDF content')
            if b'%PDF-' not in data[:1024]:
                raise ValueError('URL returned non-PDF content')
            return bytes(data)
