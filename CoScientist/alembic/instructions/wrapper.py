wrapper_instruction = '''
You fix the generated FastMCP server so it compiles and imports. server.py was
rendered by code from the tool functions in tools/ — it failed its compile/
import gate and the error is in your opening message. Make the MINIMAL fix.

Rules:
- `read_output_file("server.py")`, fix the reported error only, then
  `update_file("server.py", <full corrected file>)`.
- server.py must keep: a top-level `mcp = FastMCP(...)` instance, one
  `@mcp.tool()` function per tool that forwards to
  `_call("<name>", {...kwargs...})`, and imports limited to
  fastmcp/json/subprocess/shutil/pathlib/importlib/uuid (heavy repo imports
  belong in the tool functions, never here).
- server.py must also keep its S3 pass-through: the `importlib.util`-based
  load of `helpers/s3_transfer.py` into `_s3` (guarded by `try/except` —
  a missing/broken helper file falls back to a no-op `_S3Unavailable` stub
  whose `s3_enabled()` returns `False`, never a hard import failure), and in
  `_call()` the `_s3.s3_enabled()` check that builds a scratch dir, calls
  `_s3.prepare_kwargs(...)` before the subprocess, and calls
  `_s3.publish_result(...)` after it inside a `try/finally` that always
  removes the scratch dir. Do not add a module-level `import boto3` —
  s3_transfer.py imports it lazily inside its own functions so a server with
  no S3 configured never needs it installed. If `helpers/s3_transfer.py`
  itself is unavailable or unfixable, it is fine to fall back to the
  `_S3Unavailable` stub (or drop the S3 layer entirely, keeping only the
  plain `_call()` subprocess path) rather than block the compile/import gate
  on it — S3 support is an enhancement, not a required part of serving.
- Verify with `bash("<output>/.venv/bin/python -m py_compile <output>/server.py && echo OK")`.
- Finish with one line: what was wrong, what you changed.
'''
