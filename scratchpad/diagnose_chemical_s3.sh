#!/bin/sh
# Run on the deployment host. It answers one question: can the chemical MCP
# server reach S3, and where does it write?
set -u

C=$(docker ps --filter name=chemical --format '{{.Names}}' | head -1)
if [ -z "$C" ]; then
  echo "No running container with 'chemical' in the name."
  docker ps -a --format '{{.Names}}\t{{.Status}}'
  exit 1
fi
echo "container: $C"

# The image runs its own virtual environment. The system interpreter has no
# boto3 and no server package, so every probe below must use this path.
PY=/app/.venv/bin/python

echo
echo "--- 1. which compose file started it, and how old the image is."
echo "    #336 changed the build context to the repository root."
docker inspect -f '{{.Config.Image}} created {{.Created}}' "$C"
docker inspect -f 'compose file: {{index .Config.Labels "com.docker.compose.project.config_files"}}' "$C"

echo
echo "--- 2. S3 environment. An empty endpoint sends boto3 to real AWS."
docker exec "$C" env | grep -i 's3\|proxy' | sed 's/\(KEY=\).*/\1<set>/'

echo
echo "--- 3. the first exception, not the stream teardown that follows it."
docker logs "$C" --since 6h 2>&1 | grep -n -i \
  'error\|exception\|traceback\|botocore\|endpoint\|credential' | head -40

echo
echo "--- 4. the cross-repository copy of the shared S3 client."
docker exec -w /app "$C" "$PY" -c \
  'import CoScientist.paper_parser.s3_connection as m; print("import ok", m.__file__)'

echo
echo "--- 5. a real upload, timed. A hang here is the bug."
docker exec -i -w /app "$C" "$PY" - <<'PY'
import time
from server.service_resources import s3_service
print("endpoint:", s3_service.endpoint)
print("bucket:  ", s3_service.bucket_name)
t = time.time()
try:
    key = s3_service.upload_bytes("ephemeral/_probe", "probe.txt", b"probe")
    print("uploaded:", key, "in %.1fs" % (time.time() - t))
except Exception as e:
    print("failed after %.1fs: %r" % (time.time() - t, e))
PY

echo
echo "--- 6. what is actually in the bucket, new prefix and old."
docker exec -w /app "$C" "$PY" -c \
  'from server.service_resources import s3_service as s; print("\n".join(s.list_objects("ephemeral/")[:30]) or "(nothing under ephemeral/)")'
docker exec -w /app "$C" "$PY" -c \
  'from server.service_resources import s3_service as s; print("\n".join(s.list_objects("chemical_mcp/")[:10]) or "(nothing under the old chemical_mcp/)")'
