"""Run one CoScientist web session headless and log every event.

usage: run_session.py <title> <prompt-file> [--dataset URL] [--timeout S]
The session is a normal web session: it shows up in the UI, has a graph, and
can be exported. Events go to runs/<title>_<session>.jsonl.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
import websockets

BASE = "127.0.0.1:8000"
HERE = Path(__file__).resolve().parent


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("title")
    ap.add_argument("prompt_file")
    ap.add_argument("--dataset")
    ap.add_argument("--language")
    ap.add_argument("--timeout", type=int, default=6 * 3600)
    a = ap.parse_args()
    prompt = Path(a.prompt_file).read_text().strip()

    async with httpx.AsyncClient(base_url=f"http://{BASE}", timeout=60) as http:
        users = (await http.get("/api/users")).json()["users"]
        user = next((u for u in users if u["nickname"] == "demo"), None)
        if user is None:
            user = (await http.post("/api/users", json={"nickname": "demo"})).json()["user"]
        r = await http.post(f"/api/users/{user['id']}/sessions", json={"title": a.title})
        body = r.json()
        sid = (body.get("session") or body)["id"]
    log = HERE / f"{a.title}_{sid[-8:]}.jsonl"
    print("user", user["id"], "session", sid, "log", log, flush=True)

    url = f"ws://{BASE}/ws?user_id={user['id']}&session_id={sid}"
    start = time.time()
    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        if a.dataset:
            await ws.send(json.dumps({"type": "set_dataset_url", "dataset_url": a.dataset}))
        if a.language:
            await ws.send(json.dumps({"type": "set_report_language", "report_language": a.language}))
        await ws.send(json.dumps({"type": "chat_message", "message": prompt}))
        with open(log, "a") as f:
            while time.time() - start < a.timeout:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    await ws.send(json.dumps({"type": "ping"}))
                    continue
                ev = json.loads(raw)
                if ev.get("type") in ("pong", "metrics"):
                    continue
                ev["_t"] = round(time.time() - start, 1)
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                f.flush()
                if ev.get("type") in ("final_response", "chat_rejected", "dataset_url_rejected"):
                    print(ev.get("type"), str(ev.get("message") or ev.get("text") or "")[:300], flush=True)
                    if ev["type"] != "dataset_url_rejected":
                        break
    print("elapsed", round(time.time() - start), flush=True)


asyncio.run(main())
