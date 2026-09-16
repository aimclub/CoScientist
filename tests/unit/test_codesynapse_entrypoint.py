"""Process-boundary tests for the Codesynapse A2A façade entry point."""

from CoScientist.integrations.codesynapse import __main__ as entrypoint


def test_facade_entrypoint_uses_one_worker_for_process_local_run_state(monkeypatch):
    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(entrypoint.uvicorn, "run", fake_run)
    monkeypatch.setattr(
        entrypoint,
        "create_app",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("factory must be loaded by Uvicorn workers")),
    )
    monkeypatch.setenv("CODESYNAPSE_A2A_WORKERS", "1")

    entrypoint.main()

    assert captured["app"] == "CoScientist.integrations.codesynapse.__main__:create_app_for_uvicorn"
    assert captured["factory"] is True
    assert captured["workers"] == 1
