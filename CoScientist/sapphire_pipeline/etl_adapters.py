"""S3 source and metadata hooks for the existing ETL pipeline."""

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
