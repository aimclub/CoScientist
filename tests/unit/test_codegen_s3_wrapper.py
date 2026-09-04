"""server.py's S3 pass-through: a deterministic hook around ``_call``, never a
module-level boto3 import (the served venv might not have S3 configured at
all, and s3_transfer.py itself only imports boto3 lazily inside its own
functions — see CoScientist/alembic/tools/scripts/s3_transfer.py).

The first half is text-level (what the rendered source contains); the second
half (``# ── _call(): exec-based behavioural tests`` down) actually executes
the rendered server.py next to the real helper, with fastmcp stubbed out and
subprocess.run replaced, to catch regressions the text checks cannot: basename
collisions on download/upload, and scratch-dir cleanup on every path.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

from _codegen_loader import load_codegen

cg = load_codegen()

_REAL_RUN_FUNCTION = (
    Path(__file__).resolve().parents[2]
    / "CoScientist" / "alembic" / "tools" / "scripts" / "run_function.py"
)
_REAL_S3_TRANSFER = (
    Path(__file__).resolve().parents[2]
    / "CoScientist" / "alembic" / "tools" / "scripts" / "s3_transfer.py"
)

_SIG = {"name": "predict", "params": [("input_path", "str", None)], "doc": "Run predict."}
_S3_ENV_VARS = ("ENDPOINT_URL", "ACCESS_KEY", "SECRET_KEY", "BUCKET_NAME", "S3_PRESIGN_EXPIRATION")
_SENTINEL = "<<<ALEMBIC_RESULT>>>"


# ── render_server: the rendered text itself ─────────────────────────────────

def test_rendered_server_compiles():
    server = cg.render_server("demo", [_SIG])

    compile(server, "server.py", "exec")


def test_rendered_server_has_no_module_level_boto3_import():
    server = cg.render_server("demo", [_SIG])

    assert "import boto3" not in server


def test_rendered_server_loads_the_s3_helper_by_file_path():
    server = cg.render_server("demo", [_SIG])

    assert "helpers" in server and "s3_transfer.py" in server
    assert "spec_from_file_location" in server
    assert "_s3_spec.loader.exec_module(_s3)" in server


def test_rendered_server_guards_the_helper_load_with_a_fallback():
    """A missing/broken helpers/s3_transfer.py must degrade to S3-off, not
    take the whole server import down (MAJOR 6)."""
    server = cg.render_server("demo", [_SIG])

    assert "except Exception" in server
    assert "_S3Unavailable" in server
    assert "s3_enabled() -> bool" in server or "def s3_enabled" in server


def test_rendered_server_call_gates_on_s3_enabled():
    server = cg.render_server("demo", [_SIG])

    assert "_s3.s3_enabled()" in server
    assert "_s3.prepare_kwargs(" in server
    assert "_s3.publish_result(" in server
    assert "_s3.call_prefix(" in server


def test_rendered_server_reads_headers_defensively():
    server = cg.render_server("demo", [_SIG])

    assert "get_http_headers" in server
    assert "except Exception" in server


def test_rendered_server_scratch_cleanup_is_in_a_finally():
    """MAJOR 5: the scratch dir must be removed on every path (success,
    tool failure, parse failure), not only after a successful publish."""
    server = cg.render_server("demo", [_SIG])

    call_body = server.split("def _call(", 1)[1]
    assert "finally:" in call_body
    assert call_body.index("finally:") > call_body.index("try:")
    assert "shutil.rmtree(scratch, ignore_errors=True)" in call_body


def test_without_s3_helper_available_the_call_path_is_unchanged_in_shape():
    """The plain (no-S3) call path — subprocess + sentinel parse — must still
    be exactly what it was before S3 support existed."""
    server = cg.render_server("demo", [_SIG])

    assert '_RUNNER = str(_OUT / "helpers" / "run_function.py")' in server
    assert "subprocess.run([_PYTHON, _RUNNER, str(_OUT), tool, json.dumps(kwargs)]" in server
    assert "_SENTINEL = " in server


# ── write_server: both helpers land on disk ──────────────────────────────────

def test_write_server_copies_both_helpers(tmp_path, monkeypatch):
    out = tmp_path / "output"
    (out / "tools").mkdir(parents=True)
    (out / "tools" / "predict.py").write_text(
        "def predict(input_path: str) -> dict:\n"
        "    \"\"\"Run predict.\"\"\"\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cg, "output_dir", lambda: out)
    monkeypatch.setattr(cg, "RUN_FUNCTION_SCRIPT", _REAL_RUN_FUNCTION)
    monkeypatch.setattr(cg, "S3_TRANSFER_SCRIPT", _REAL_S3_TRANSFER)

    result = cg.write_server("demo", ["predict"])

    assert result["tools"] == ["predict"]
    assert (out / "helpers" / "run_function.py").read_text(encoding="utf-8") == (
        _REAL_RUN_FUNCTION.read_text(encoding="utf-8")
    )
    assert (out / "helpers" / "s3_transfer.py").read_text(encoding="utf-8") == (
        _REAL_S3_TRANSFER.read_text(encoding="utf-8")
    )
    compile((out / "server.py").read_text(encoding="utf-8"), "server.py", "exec")


# ── _call(): exec-based behavioural tests ────────────────────────────────────

def _clear_s3_env(monkeypatch):
    for name in _S3_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _set_s3_env(monkeypatch):
    monkeypatch.setenv("ENDPOINT_URL", "https://s3.example.com")
    monkeypatch.setenv("ACCESS_KEY", "AKIA")
    monkeypatch.setenv("SECRET_KEY", "secret")
    monkeypatch.setenv("BUCKET_NAME", "bucket")


def _install_fastmcp_stub(monkeypatch):
    """A minimal fastmcp stand-in so the rendered server can be exec'd without
    the real package installed — mirrors how a truly isolated server venv
    would behave (FastMCP + get_http_headers only)."""

    class _FastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def deco(fn):
                return fn
            return deco

        def run(self):
            pass

    fastmcp_pkg = types.ModuleType("fastmcp")
    fastmcp_pkg.FastMCP = _FastMCP
    server_pkg = types.ModuleType("fastmcp.server")
    deps_mod = types.ModuleType("fastmcp.server.dependencies")
    deps_mod.get_http_headers = lambda: {}
    monkeypatch.setitem(sys.modules, "fastmcp", fastmcp_pkg)
    monkeypatch.setitem(sys.modules, "fastmcp.server", server_pkg)
    monkeypatch.setitem(sys.modules, "fastmcp.server.dependencies", deps_mod)


def _write_rendered_server(out: Path, helper_source: str | None) -> Path:
    """Render server.py into ``out`` (its own ``_OUT``) with an optional real
    helpers/s3_transfer.py alongside it. ``None`` = no helper file at all
    (MAJOR 6 regression)."""
    out.mkdir(parents=True, exist_ok=True)
    server_path = out / "server.py"
    server_path.write_text(cg.render_server("demo", [_SIG]), encoding="utf-8")
    if helper_source is not None:
        helpers = out / "helpers"
        helpers.mkdir(parents=True, exist_ok=True)
        (helpers / "s3_transfer.py").write_text(helper_source, encoding="utf-8")
    return server_path


def _load_server_module(server_path: Path, monkeypatch):
    _install_fastmcp_stub(monkeypatch)
    spec = importlib.util.spec_from_file_location("alembic_server_under_test", server_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr


def _sentinel_stdout(result=None, ok: bool = True, error: str | None = None) -> str:
    payload = {"ok": ok, "result": result} if ok else {"ok": ok, "error": error or "boom"}
    return f"{_SENTINEL}\n{json.dumps(payload)}\n"


def test_call_without_s3_env_passes_kwargs_through_and_creates_no_scratch(tmp_path, monkeypatch):
    _clear_s3_env(monkeypatch)
    server_path = _write_rendered_server(
        tmp_path, helper_source=_REAL_S3_TRANSFER.read_text(encoding="utf-8"))
    mod = _load_server_module(server_path, monkeypatch)

    captured = {}

    def _fake_run(cmd, **kw):
        captured["kwargs_json"] = cmd[4]
        return _FakeCompleted(_sentinel_stdout({"result_path": "/x"}))

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    kwargs_in = {"input_path": "/local/data.csv"}
    result = mod._call("predict", dict(kwargs_in))

    assert json.loads(captured["kwargs_json"]) == kwargs_in
    assert result == {"result_path": "/x"}
    assert not (tmp_path / ".scratch").exists()


def test_call_with_s3_resolves_colliding_input_basenames_to_distinct_files(tmp_path, monkeypatch):
    """Regression for BLOCKER 1."""
    _set_s3_env(monkeypatch)
    server_path = _write_rendered_server(
        tmp_path, helper_source=_REAL_S3_TRANSFER.read_text(encoding="utf-8"))
    mod = _load_server_module(server_path, monkeypatch)

    class _FakeClient:
        def download_file(self, bucket, key, local_path):
            Path(local_path).write_text(f"{bucket}:{key}", encoding="utf-8")

    monkeypatch.setattr(mod._s3, "_client_factory", lambda: _FakeClient())

    captured = {}

    def _fake_run(cmd, **kw):
        # inspect the resolved kwargs (and read the downloaded files) from
        # inside the stub — _call()'s finally wipes the scratch dir as soon
        # as it returns, same as the real runner subprocess would have
        # already consumed the files by then.
        kwargs = json.loads(cmd[4])
        captured["a_path"] = kwargs["a_path"]
        captured["b_path"] = kwargs["b_path"]
        captured["a_content"] = Path(kwargs["a_path"]).read_text(encoding="utf-8")
        captured["b_content"] = Path(kwargs["b_path"]).read_text(encoding="utf-8")
        return _FakeCompleted(_sentinel_stdout({"ok_field": True}))

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    mod._call("predict", {
        "a_path": "s3://bucket-1/dir1/data.csv",
        "b_path": "s3://bucket-2/dir2/data.csv",
    })

    assert captured["a_path"] != captured["b_path"]
    assert Path(captured["a_path"]).name == "data.csv"
    assert Path(captured["b_path"]).name == "data.csv"
    assert captured["a_content"] == "bucket-1:dir1/data.csv"
    assert captured["b_content"] == "bucket-2:dir2/data.csv"


def test_call_with_s3_publishes_colliding_output_basenames_to_distinct_keys(tmp_path, monkeypatch):
    """Regression for MAJOR 2."""
    _set_s3_env(monkeypatch)
    server_path = _write_rendered_server(
        tmp_path, helper_source=_REAL_S3_TRANSFER.read_text(encoding="utf-8"))
    mod = _load_server_module(server_path, monkeypatch)

    uploaded_keys = []

    class _FakeClient:
        def upload_file(self, local_path, bucket, key):
            uploaded_keys.append(key)

        def generate_presigned_url(self, method, Params, ExpiresIn):
            return f"https://signed/{Params['Key']}"

    monkeypatch.setattr(mod._s3, "_client_factory", lambda: _FakeClient())

    f1 = tmp_path / "out1" / "result.csv"
    f1.parent.mkdir(parents=True)
    f1.write_text("1", encoding="utf-8")
    f2 = tmp_path / "out2" / "result.csv"
    f2.parent.mkdir(parents=True)
    f2.write_text("2", encoding="utf-8")

    def _fake_run(cmd, **kw):
        return _FakeCompleted(_sentinel_stdout({"a_path": str(f1), "b_path": str(f2)}))

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    result = mod._call("predict", {})

    assert result["a_path_s3_key"] != result["b_path_s3_key"]
    assert len(set(uploaded_keys)) == 2


def test_call_does_not_republish_an_echoed_input_path_from_scratch(tmp_path, monkeypatch):
    """A tool that returns its own (downloaded) input_path must not get that
    scratch file re-uploaded: the upload would duplicate the caller's own
    input, and the sibling local path dies with the scratch cleanup."""
    _set_s3_env(monkeypatch)
    server_path = _write_rendered_server(
        tmp_path, helper_source=_REAL_S3_TRANSFER.read_text(encoding="utf-8"))
    mod = _load_server_module(server_path, monkeypatch)

    uploaded = []

    class _FakeClient:
        def download_file(self, bucket, key, local_path):
            Path(local_path).write_text("in", encoding="utf-8")

        def upload_file(self, local_path, bucket, key):
            uploaded.append(key)

        def generate_presigned_url(self, method, Params, ExpiresIn):
            return f"https://signed/{Params['Key']}"

    monkeypatch.setattr(mod._s3, "_client_factory", lambda: _FakeClient())

    out_file = tmp_path / "output" / "result.csv"
    out_file.parent.mkdir(parents=True)
    out_file.write_text("out", encoding="utf-8")

    def _fake_run(cmd, **kw):
        kwargs = json.loads(cmd[4])
        # echo the downloaded input back alongside a genuine output file
        return _FakeCompleted(_sentinel_stdout(
            {"input_path": kwargs["input_path"], "result_path": str(out_file)}))

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    result = mod._call("predict", {"input_path": "s3://bucket/dir/data.csv"})

    assert "input_path_s3_key" not in result
    assert "input_path_presigned_url" not in result
    assert "result_path_s3_key" in result
    assert len(uploaded) == 1 and uploaded[0].endswith("/result_path/result.csv")


def test_call_cleans_up_scratch_dir_on_success_and_on_failure(tmp_path, monkeypatch):
    """Regression for MAJOR 5."""
    _set_s3_env(monkeypatch)
    server_path = _write_rendered_server(
        tmp_path, helper_source=_REAL_S3_TRANSFER.read_text(encoding="utf-8"))
    mod = _load_server_module(server_path, monkeypatch)

    class _FakeClient:
        def download_file(self, bucket, key, local_path):
            Path(local_path).write_text("x", encoding="utf-8")

    monkeypatch.setattr(mod._s3, "_client_factory", lambda: _FakeClient())

    fixed_uuid = types.SimpleNamespace(hex="deadbeefcafebabe")
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: fixed_uuid)
    scratch_dir = tmp_path / ".scratch" / "deadbeefcafebabe"

    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(_sentinel_stdout({"result": "ok"})))
    mod._call("predict", {"input_path": "s3://b/k/data.csv"})
    assert not scratch_dir.exists()

    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(_sentinel_stdout(ok=False, error="boom")))
    try:
        mod._call("predict", {"input_path": "s3://b/k/data.csv"})
        assert False, "expected a RuntimeError"
    except RuntimeError:
        pass
    assert not scratch_dir.exists()


def test_call_cleans_up_scratch_dir_when_an_input_download_fails(tmp_path, monkeypatch):
    """Regression for MAJOR 1 (round 2): prepare_kwargs() must run INSIDE the
    try — in the buggy version it ran before, so a download failure on the
    SECOND of several file params (S3 unreachable mid-call, a bad URI,
    S3_HTTP_MAX_BYTES tripped) left the whole scratch dir — including the
    FIRST file that already downloaded fine — on disk forever."""
    _set_s3_env(monkeypatch)
    server_path = _write_rendered_server(
        tmp_path, helper_source=_REAL_S3_TRANSFER.read_text(encoding="utf-8"))
    mod = _load_server_module(server_path, monkeypatch)

    class _FailOnSecondDownloadClient:
        def __init__(self):
            self.calls = 0

        def download_file(self, bucket, key, local_path):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("simulated network failure")
            Path(local_path).write_text("ok", encoding="utf-8")

    # _client_factory() is called fresh for EACH download — reuse ONE
    # instance across calls so its counter actually persists to the second
    # download (a lambda re-instantiating the class would reset it every time).
    shared_client = _FailOnSecondDownloadClient()
    monkeypatch.setattr(mod._s3, "_client_factory", lambda: shared_client)

    fixed_uuid = types.SimpleNamespace(hex="feedfacecafebeef")
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: fixed_uuid)
    scratch_dir = tmp_path / ".scratch" / "feedfacecafebeef"

    # subprocess.run must never even be reached — the failure happens inside
    # prepare_kwargs(), before the (stubbed) runner would be invoked.
    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda cmd, **kw: (_ for _ in ()).throw(
            AssertionError("subprocess.run must not run after a failed download")))

    try:
        mod._call("predict", {
            "a_path": "s3://bucket/dir1/data.csv",
            "b_path": "s3://bucket/dir2/data2.csv",
        })
        assert False, "expected the download failure to propagate"
    except RuntimeError:
        pass

    assert not scratch_dir.exists()


def test_call_survives_a_missing_s3_helper_file(tmp_path, monkeypatch):
    """Regression for MAJOR 6: no helpers/s3_transfer.py at all — the server
    must still import and _call() must still work the plain (no-S3) way."""
    _set_s3_env(monkeypatch)   # even with S3 "on", a missing helper => S3 off
    server_path = _write_rendered_server(tmp_path, helper_source=None)
    mod = _load_server_module(server_path, monkeypatch)

    assert mod._s3.s3_enabled() is False

    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(_sentinel_stdout({"ok_field": True})))

    result = mod._call("predict", {"input_path": "/local/x.csv"})

    assert result == {"ok_field": True}


def test_call_survives_a_broken_s3_helper_file(tmp_path, monkeypatch):
    """Regression for MAJOR 6: a helper that raises on import must not take
    the server down either."""
    _set_s3_env(monkeypatch)
    server_path = _write_rendered_server(tmp_path, helper_source="raise RuntimeError('boom')\n")
    mod = _load_server_module(server_path, monkeypatch)

    assert mod._s3.s3_enabled() is False
