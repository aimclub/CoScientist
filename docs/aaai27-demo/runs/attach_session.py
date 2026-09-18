"""Re-attach to a running web session and keep appending its events to the log.

usage: attach_session.py <user_id> <session_id> <events.jsonl> <t_offset_seconds>
Used when the driver that started the run has died; the run itself lives in the
web server. Ends on final_response.
"""
import asyncio, json, sys, time
import websockets

uid, sid, log, off = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
SEND = open(sys.argv[sys.argv.index("--send") + 1]).read().strip() if "--send" in sys.argv else None


async def main():
    start = time.time()
    async with websockets.connect(f"ws://127.0.0.1:8000/ws?user_id={uid}&session_id={sid}",
                                  max_size=None, ping_interval=None) as ws:
        if SEND:
            await ws.send(json.dumps({"type": "chat_message", "message": SEND}))
        with open(log, "a") as f:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    await ws.send(json.dumps({"type": "ping"})); continue
                ev = json.loads(raw)
                if ev.get("type") in ("pong", "metrics", "connected", "session_snapshot"):
                    continue
                ev["_t"] = round(off + time.time() - start, 1)
                f.write(json.dumps(ev, ensure_ascii=False) + "\n"); f.flush()
                if ev.get("type") in ("final_response", "chat_rejected"):
                    break

asyncio.run(main())
