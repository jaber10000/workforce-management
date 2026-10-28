"""Deployment smoke test - run against a live URL after every deploy (stdlib only).

    python -m app.scripts.smoke_test https://roster.example.com --user smoke_mgr --password '...'
    SMOKE_USER=... SMOKE_PASSWORD=... python -m app.scripts.smoke_test http://localhost:8000

Create a dedicated low-privilege `manager` account for this (create_user smoke_mgr --role manager).
Read-only except for the login audit row. Exit code 0 = all checks passed.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

XLSX = b"PK"


def call(base, path, token=None, method="GET", body=None, origin=None):
    req = urllib.request.Request(base + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if origin:
        req.add_header("Origin", origin)
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data=data, timeout=20) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--user", default=os.getenv("SMOKE_USER"))
    ap.add_argument("--password", default=os.getenv("SMOKE_PASSWORD"))
    ap.add_argument("--origin", default=None, help="frontend origin to test CORS with (default: base url)")
    a = ap.parse_args(argv)
    base = a.base_url.rstrip("/")
    api = base + "/api/v1"
    origin = a.origin or base
    results: list[tuple[str, bool, str]] = []

    def check(name, ok, info=""):
        results.append((name, bool(ok), info))
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {info}")

    s, b, h = call(base, "/health")
    check("health", s == 200 and b"ok" in b, f"-> {s}")
    s, b, _ = call(base, "/ready")
    check("database ready", s == 200, f"-> {s}")
    if base.startswith("https://"):
        s, _, h = call(base, "/health")
        check("HSTS header", any(k.lower() == "strict-transport-security" for k in h))
        s, _, _ = call("http://" + base[len("https://"):], "/health")
        check("http redirects to https (or is closed)", s in (200, 301, 308) or s == 0, f"-> {s}")
    s, _, h = call(api, "/auth/me")
    check("protected endpoint rejects anonymous", s == 401, f"-> {s}")
    s, _, h = call(api, "/auth/login", method="POST", body={"username": "nobody", "password": "wrong-password"})
    check("wrong password rejected", s == 401, f"-> {s}")
    s, _, h = call(api, "/auth/login", method="OPTIONS", origin="https://evil.example")
    check("CORS blocks foreign origin", not any(k.lower() == "access-control-allow-origin" and v == "https://evil.example"
                                               for k, v in h.items()))
    s, b, _ = call(base, "/docs")
    if base.startswith("https://"):
        check("API docs are not public", s in (401, 403, 404), f"-> {s}")

    if a.user and a.password:
        t0 = time.time()
        s, b, _ = call(api, "/auth/login", method="POST", body={"username": a.user, "password": a.password})
        ok = s == 200
        check("login", ok, f"-> {s} ({time.time() - t0:.1f}s)")
        if ok:
            token = json.loads(b)["access_token"]
            s, b, _ = call(api, "/auth/me", token)
            check("session identity", s == 200 and json.loads(b)["username"] == a.user)
            s, b, _ = call(api, "/roster/versions?limit=5", token)
            check("roster versions readable", s == 200, f"-> {s}")
            s, b, _ = call(api, "/employees?limit=1", token)
            check("employees readable", s == 200, f"-> {s}")
            s, b, h = call(api, "/exports/employees.xlsx", token)
            check("Excel export works", s == 200 and b[:2] == XLSX, f"-> {s}, {len(b)} bytes")
    else:
        print("(no --user/--password: authenticated checks skipped)")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
