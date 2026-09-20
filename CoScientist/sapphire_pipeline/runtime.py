"""Adapter to papers_processing_refactoring; imported only by the actual run command."""
from __future__ import annotations

import sys
import types
from pathlib import Path

# Follow the standalone ETL entry point: avoid initializing the agent application.
if 'CoScientist' not in sys.modules:
    package = types.ModuleType('CoScientist')
    package.__path__ = [str(Path(__file__).resolve().parents[1])]
    package.__package__ = 'CoScientist'
    sys.modules['CoScientist'] = package

from CoScientist.papers_processing_refactoring.app.main_process import (
    build_shared_services, build_state_store, settings,
)
from CoScientist.papers_processing_refactoring.domain.entities import Article
from CoScientist.papers_processing_refactoring.etl import (
    ETLContext, ETLPipeline, FetchStep, ParseStep, HtmlCleaningStep,
    ImageFilteringStep, ImageCaptioningStep, MetadataExtractionStep,
    ChunkingStep, EmbeddingStep, PublishStep,
)

from .client import normalize_doi


from .etl_adapters import S3Source


class RAGBackend:
    def __init__(self):
        """Create configured ETL services and load existing Chroma IDs and DOIs.

        The in-memory deduplication sets represent the selected collection at
        startup and are extended after successful ingestion in this process.
        """
        self.settings = settings
        self.services = build_shared_services(settings)
        self.public = self.services['public_store']
        self.collection = self.services['vector_store'].collection
        self.article_ids = set()
        self.dois = set()
        # Scan existing metadata once, including legacy DOI URL/case variants.
        offset = 0
        while True:
            page = self.collection.get(limit=1000, offset=offset, include=['metadatas'])
            if not page['ids']:
                break
            for metadata in page['metadatas']:
                self.remember(metadata or {})
            offset += len(page['ids'])

    def remember(self, metadata):
        """Add an article ID and normalized DOI to the in-memory duplicate index.

        Ignore missing identifiers and invalid DOI values.
        """
        if metadata.get('article_id'):
            self.article_ids.add(metadata['article_id'])
        doi = normalize_doi(metadata.get('doi'))
        if doi:
            self.dois.add(doi)

    def contains(self, metadata):
        """Return whether an article ID or already-normalized DOI is indexed.

        OpenAlex IDs are not used for deduplication. This checks in-memory sets
        rather than issuing a fresh Chroma query.
        """
        return bool(
            metadata.get('article_id') in self.article_ids
            or metadata.get('doi') in self.dois
        )

    def upload(self, key, pdf):
        """Write PDF bytes to the supplied key in the configured public S3 bucket."""
        self.public.client.put_object(
            Bucket=self.public.bucket, Key=key, Body=pdf, ContentType='application/pdf',
        )

    def ingest(self, article_id, name, metadata):
        """Run the original papers ETL for a PDF already uploaded to S3.

        Args:
            article_id: MD5 of the PDF bytes, used for state and Chroma records.
            name: Article name passed to the ETL context.
            metadata: Article metadata including domain and s3_key.

        Reuse intermediate states, or clear a previous completed publication state
        when reprocessing. After ETL, verify that Chroma contains article chunks
        and remember their identity. Service and processing errors propagate.
        """
        article = Article(
            id=article_id, name=name, domain=metadata['domain'], metadata=metadata,
            source_type='remote', source_ref=f"s3://{self.public.bucket}/{metadata['s3_key']}",
        )
        with build_state_store(self.settings) as state:
            # A completed ETL whose vectors were removed must be rebuilt.
            if state.get_status(article_id, 'publish') == 'done':
                state.clear_data(article_id)
            ctx = ETLContext(
                article=article, state_manager=state,
                artifact_store=self.services['artifact_store'], public_store=self.public,
                vector_store=self.services['vector_store'], llm=self.services['llm_model'],
                embedding_model=self.services['embedding_model'],
            )
            ETLPipeline([
                FetchStep(S3Source(self.public)), ParseStep(), HtmlCleaningStep(),
                ImageFilteringStep(), ImageCaptioningStep(), MetadataExtractionStep(),
                ChunkingStep(),
                EmbeddingStep(), PublishStep(),
            ]).run(ctx)
            if not self.collection.get(where={'article_id': article_id}, limit=1, include=[])['ids']:
                raise RuntimeError('ETL completed without publishing vectors')
        self.remember(dict(metadata, article_id=article_id))
