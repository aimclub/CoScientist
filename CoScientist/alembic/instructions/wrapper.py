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
  fastmcp/json/subprocess/pathlib (heavy repo imports belong in the tool
  functions, never here).
- Verify with `bash("<output>/.venv/bin/python -m py_compile <output>/server.py && echo OK")`.
- Finish with one line: what was wrong, what you changed.
'''
