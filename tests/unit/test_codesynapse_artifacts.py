import asyncio
import hashlib

from CoScientist.integrations.codesynapse.artifact_client import CodesynapseArtifactClient


class _Response:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload


def test_artifact_client_uses_capability_for_grant_and_finalize_but_not_presigned_put():
    async def scenario():
        calls = []

        async def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if url.endswith("/grant"):
                return _Response(payload={"upload_url": "http://storage/upload", "artifact_id": "artifact-1"})
            return _Response(status_code=204)

        part = await CodesynapseArtifactClient(
            upload_request_url="http://codesynapse/artifacts/grant",
            finalize_url="http://codesynapse/artifacts/finalize",
            capability_token="artifact-capability",
            request=request,
        ).upload_text(
            name="final_report",
            filename="final_report.md",
            text="# Report",
            mime_type="text/markdown",
        )

        assert part.artifact_id == "artifact-1"
        assert part.checksum_sha256 == hashlib.sha256(b"# Report").hexdigest()
        assert calls[0][2]["headers"] == {"Authorization": "Bearer artifact-capability"}
        assert "headers" not in calls[1][2]
        assert calls[2][2]["headers"] == {"Authorization": "Bearer artifact-capability"}

    asyncio.run(scenario())
