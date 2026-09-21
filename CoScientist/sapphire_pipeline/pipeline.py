from __future__ import annotations

import hashlib
import logging
import math
from collections import Counter
from itertools import islice

from .client import normalize_doi, openalex_id

logger = logging.getLogger(__name__)


def allowed_domains(publication):
    """Accept positive AI/chembio scores only when no photonics score is positive.

    Missing or malformed domain entries do not establish domain membership.
    These Sapphire scores are separate from the OpenAlex domain/field taxonomy.
    """
    domains = publication.get('domains')
    if not isinstance(domains, list):
        return False
    positive = set()
    for domain in domains:
        if not isinstance(domain, dict):
            continue
        name, score = domain.get('name'), domain.get('score')
        if (isinstance(name, str) and type(score) in (int, float)
                and math.isfinite(score) and score > 0):
            positive.add(name.strip().lower())
    return bool(positive & {'ai', 'chembio'}) and 'photonics' not in positive


def classification(work):
    """Return domain and field display names from a work primary topic.

    Raise ValueError if either name is missing or the domain is unsafe for
    use as a component of the initial S3 object key.
    """
    topic = work.get('primary_topic') or {}
    domain = (topic.get('domain') or {}).get('display_name')
    field = (topic.get('field') or {}).get('display_name')
    if not all(isinstance(value, str) and value.strip() for value in (domain, field)):
        raise ValueError('Work has no primary_topic.domain/field.display_name')
    if any(char in domain for char in ('/', '\\', '\x00')) or domain in ('.', '..'):
        raise ValueError('Domain is not a safe S3 path component')
    return domain, field


def pdf_urls(publication, work):
    """Return unique, nonempty PDF candidate URLs in download priority order.

    Prefer the publication URL, then best OA and primary locations not marked
    closed, followed by work locations explicitly marked open access.
    """
    candidates = [publication.get('pdf_url')]
    for key in ('best_oa_location', 'primary_location'):
        location = work.get(key) or {}
        if location.get('is_oa') is not False:
            candidates.append(location.get('pdf_url'))
    for location in work.get('locations') or []:
        if location.get('is_oa') is True:
            candidates.append(location.get('pdf_url'))
    return list(dict.fromkeys(url.strip() for url in candidates if isinstance(url, str) and url.strip()))


class SapphirePipeline:
    """Backend implements contains(metadata), upload(key, bytes), ingest(...)."""

    def __init__(self, client, backend):
        """Bind the Sapphire client and the backend used for deduplication and ETL."""
        self.client = client
        self.backend = backend

    def process(self, publication):
        """Process one publication and return its ingestion or skip reason.

        Check domain scores, DOI, open access, and the work ID; enrich metadata; try PDF candidates;
        check the PDF hash; then upload to S3 and run ETL. Return ingested,
        domain_filtered, already_in_rag, not_open_access, missing_openalex_id, or no_usable_pdf.
        Candidate download errors are logged and skipped; other errors propagate.
        """
        if not allowed_domains(publication):
            return 'domain_filtered'
        identifier = openalex_id(publication.get('openalex_id'))
        metadata = {
            'openalex_id': identifier or '',
            'doi': normalize_doi(publication.get('doi')) or '',
            'sapphire_publication_id': str(publication.get('id') or ''),
        }
        if self.backend.contains(metadata):
            return 'already_in_rag'
        if publication.get('is_open_access') is not True:
            return 'not_open_access'
        if not identifier:
            return 'missing_openalex_id'
        work = self.client.work(identifier)
        domain, field = classification(work)
        metadata.update(domain=domain, field=field)
        metadata['doi'] = metadata['doi'] or normalize_doi(work.get('doi')) or ''
        if self.backend.contains(metadata):
            return 'already_in_rag'
        for url in pdf_urls(publication, work):
            try:
                pdf = self.client.download_pdf(url)
            except Exception:
                logger.warning('PDF candidate unavailable for %s', identifier, exc_info=True)
                continue
            # Same content ID as LocalSource: catches previously ingested local PDFs.
            article_id = hashlib.md5(pdf).hexdigest()
            if self.backend.contains(dict(metadata, article_id=article_id)):
                return 'already_in_rag'
            key = f'articles/{domain}/{article_id}/paper.pdf'
            metadata.update(pdf_url=url, s3_key=key, ingestion_source='sapphire')
            self.backend.upload(key, pdf)
            self.backend.ingest(article_id, publication.get('name') or work.get('display_name') or identifier, metadata)
            return 'ingested'
        return 'no_usable_pdf'

    def run(self, max_articles=None):
        """Process publications sequentially and return counters by outcome.

        Args:
            max_articles: Maximum number of records to inspect, including skips
                and failures; None processes records until pagination ends.

        Count per-publication exceptions as failed and continue. Page-fetch errors
        propagate. Raise ValueError when a supplied limit is not positive.
        """
        if max_articles is not None and max_articles < 1:
            raise ValueError('max_articles must be positive')
        counts = Counter()
        for publication in islice(self.client.publications(), max_articles):
            counts['seen'] += 1
            progress = f"{counts['seen']}/{max_articles}" if max_articles is not None else str(counts['seen'])
            logger.info(
                "[%s] Processing publication: %s | %s",
                progress, publication.get('openalex_id'), publication.get('name') or 'Untitled',
            )
            try:
                outcome = self.process(publication)
            except Exception:
                logger.exception('Publication failed: %s', publication.get('openalex_id'))
                outcome = 'failed'
            counts[outcome] += 1
            logger.info('[%s] %s: %s', progress, publication.get('openalex_id'), outcome)
        return dict(counts)
