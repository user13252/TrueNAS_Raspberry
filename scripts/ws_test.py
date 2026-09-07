"""End-to-end WebSocket test for the TrueNAS Scale RPi backend.

Usage:
    python scripts/ws_test.py [host] [port]

Runs the full round-trip: set_options -> login_ex -> auth.me ->
service.query -> subscribe -> service.update -> collection_update ->
unsubscribe -> logout -> denied.
"""
import asyncio
import json
import sys

import websockets


async def main(host: str = "127.0.0.1", port: int = 80):
    url = f"ws://{host}:{port}/api/current"
    print(f"Connecting to {url} ...")

    async with websockets.connect(
        url,
        max_size=2**20,
        extra_headers={"Origin": f"http://{host}:{port}"},
    ) as ws:
        async def call(method, params, expect=None):
            await ws.send(json.dumps({
                "jsonrpc": "2.0", "id": expect, "method": method,
                "params": params,
            }))
            r = json.loads(await ws.recv())
            assert r.get("id") == expect or "result" in r or "error" in r
            return r

        # 1. core.set_options
        r = await call("core.set_options", [{"legacy_jobs": False}], 1)
        assert "result" in r, r
        print("1. core.set_options OK")

        # 2. auth.login_ex
        r = await call("auth.login_ex",
                       [[{"mechanism": "PASSWORD_PLAIN",
                          "username": "admin", "password": "admin"}]], 2)
        assert r["result"]["auth_result"] == "SUCCESS", r
        print("2. auth.login_ex OK")

        # 3. auth.me (authorized through connection context)
        r = await call("auth.me", [], 3)
        assert r["result"]["username"] == "admin", r
        print("3. auth.me OK")

        # 4. service.query
        r = await call("service.query", [], 4)
        assert isinstance(r["result"], list) and len(r["result"]) >= 18, r
        print(f"4. service.query OK ({len(r['result'])} services)")

        # 5. core.subscribe to service.query
        r = await call("core.subscribe", [["service.query"]], 5)
        sub_id = r["result"]
        print(f"5. core.subscribe OK ({sub_id})")

        # 6. service.update triggers a push
        r = await call("service.update", ["cifs", {"enable": True}], 6)
        assert "result" in r, r
        print("6. service.update OK")

        # 7. wait for collection_update
        got = False
        while not got:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
            except asyncio.TimeoutError:
                break
            if msg.get("method") == "collection_update":
                got = True
                assert msg["params"]["collection"] == "service.query"
                print("7. collection_update received:",
                      msg["params"]["msg"])
        assert got, "No collection_update received!"
        print("   subscription push OK")

        # 8. core.unsubscribe
        r = await call("core.unsubscribe", [[sub_id]], 7)
        assert r["result"] is None, r
        print("8. core.unsubscribe OK")

        # 9. auth.logout
        r = await call("auth.logout", [], 8)
        assert r["result"] is None, r
        print("9. auth.logout OK")

        # 10. post-logout: unauthenticated call must be denied
        r = await call("pool.query", [], 9)
        assert r["error"]["code"] == -32001, r
        print("10. post-logout denial OK")

        print()
        print("ALL WEBSOCKET TESTS PASSED")


if __name__ == "__main__":
    args = sys.argv[1:]
    host = args[0] if args else "127.0.0.1"
    port = int(args[1]) if len(args) > 1 else 80
    asyncio.run(main(host, port))