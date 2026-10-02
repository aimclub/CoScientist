"""S3 source and metadata hooks for the existing ETL pipeline."""

class AddIngestionSource:
    """Attach the ingestion origin to chunks without changing bibliographic source."""

    def execute(self, ctx):
        """Copy only ingestion_source from article metadata to every chunk."""
        source = (ctx.article.metadata or {}).get('ingestion_source')
        if not isinstance(source, str) or not source.strip():
            return
        for chunks in ctx.chunks.values():
            for chunk in chunks:
                chunk.metadata = {**(chunk.metadata or {}), 'ingestion_source': source}


class S3Source:
    def __init__(self, store):
        """Bind the S3 artifact store containing the source PDF."""
        self.store = store

    def fetch(self, article):
        """Read PDF bytes from the article metadata s3_key in the store bucket.

        Always close the response body after reading; S3 and read errors propagate.
        """
        response = self.store.client.get_object(
            Bucket=self.store.bucket, Key=article.metadata['s3_key'],
        )
        try:
            return response['Body'].read()
        finally:
            response['Body'].close()
