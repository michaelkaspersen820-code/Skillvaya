"""OWNLINK-20261116: Michael's own PC connection (his own "Desktop Commander"), independent of Kaspersen.

An AI app (Claude, or any other that speaks MCP) calls   POST /mcp/<secret>   on this server. The call is put in
a queue; the small agent on Michael's PC (OwnPCLink\\ownlink_agent.py) long-polls for it over an outgoing
connection, does the work on the PC and posts the result back. No port is opened on the PC.

Who may use it: only someone who has the secret address. The secret is made on the PC; only its SHA-256 is stored
here (kai_secrets: ownlink_token_hash), written by a request signed with the PC's Ed25519 key. The agent's poll and
result calls are signed with that same key. No usage limit, no cost."""
import hashlib, hmac, json, secrets, threading, time

A = None
VERIFY = None
S = {"jobs": {}, "queue": [], "cv": threading.Condition(), "seen": 0.0, "last_ts": 0.0, "hash": "", "hash_at": 0.0,
     "fails": {}, "tools": []}
WAIT = 50          # seconds a tool call waits for the PC before answering "still running"
KEEP = 3600        # seconds a finished or running job is remembered


def bind(a, verify):
    global A, VERIFY
    A, VERIFY = a, verify


def _token_hash():
    if time.time() - S["hash_at"] > 60:
        try:
            with A.conn() as c:
                r = c.execute("SELECT value FROM kai_secrets WHERE name=?", ("ownlink_token_hash",)).fetchone()
            S["hash"] = (r["value"] if r else "") or ""
        except Exception:
            pass
        S["hash_at"] = time.time()
    return S["hash"]


def _signed(d):
    data = VERIFY(d, 120) if isinstance(d, dict) else None
    if not data:
        return None
    with S["cv"]:
        if float(data.get("ts", 0)) <= S["last_ts"]:
            return None
        S["last_ts"] = float(data["ts"])
    return data


def _gc():
    now = time.time()
    for k in [k for k, j in S["jobs"].items() if j["created"] < now - KEEP]:
        S["jobs"].pop(k, None)


def handle_agent(h, path, d):
    """/api/own/register | poll | result - called only by the agent on the PC (signed)."""
    data = _signed(d)
    if not data:
        return h.sendj({"error": "Not authorised."}, 401)
    if path == "/api/own/register":
        th = str(data.get("token_hash", ""))
        if len(th) != 64:
            return h.sendj({"error": "Bad token hash."}, 400)
        with A.conn() as c:
            c.execute("INSERT INTO kai_secrets(name,value,updated_at) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET "
                      "value=excluded.value, updated_at=excluded.updated_at", ("ownlink_token_hash", th, A.now()))
        S["hash"], S["hash_at"] = th, time.time()
        if isinstance(data.get("tools"), list):
            S["tools"] = data["tools"]
        return h.sendj({"ok": True})
    if path == "/api/own/poll":
        if isinstance(data.get("tools"), list) and data["tools"]:
            S["tools"] = data["tools"]
        deadline = time.time() + 25
        with S["cv"]:
            S["seen"] = time.time()
            while not S["queue"] and time.time() < deadline:
                S["cv"].wait(max(0.1, deadline - time.time()))
            S["seen"] = time.time()
            out = []
            while S["queue"] and len(out) < 4:
                jid = S["queue"].pop(0); j = S["jobs"].get(jid)
                if j:
                    j["status"] = "running"; out.append({"id": jid, "tool": j["tool"], "args": j["args"]})
        return h.sendj({"jobs": out, "need_tools": not S["tools"]})
    if path == "/api/own/result":
        with S["cv"]:
            j = S["jobs"].get(str(data.get("id", "")))
            if j:
                j["status"] = "done"; j["result"] = data.get("result"); S["cv"].notify_all()
        return h.sendj({"ok": True})
    return h.sendj({"error": "Not found"}, 404)


def _text(t, err=False):
    return {"content": [{"type": "text", "text": t}], "isError": bool(err)}


def _wait(jid, seconds):
    deadline = time.time() + max(0, min(float(seconds), WAIT))
    with S["cv"]:
        j = S["jobs"].get(jid)
        while j and j["status"] != "done" and time.time() < deadline:
            S["cv"].wait(max(0.05, deadline - time.time()))
        if not j:
            return _text("No such job (jobs are kept for one hour).", True)
        if j["status"] == "done":
            r = j["result"]
            return r if isinstance(r, dict) and "content" in r else _text(json.dumps(r)[:200000])
    return _text(f"Still running on the PC after {int(seconds)} s. Job id: {jid}. Call job_result with this id to get the "
                 f"output when it is finished (you can keep working meanwhile).")


def _call(name, args):
    if name == "job_result":
        return _wait(str(args.get("id", "")), args.get("wait_s", 30))
    if time.time() - S["seen"] > 70:
        return _text("The PC is not connected right now (switched off, asleep, offline, or the PC link program is not running).", True)
    jid = secrets.token_hex(6)
    with S["cv"]:
        _gc()
        S["jobs"][jid] = {"tool": name, "args": args, "status": "queued", "result": None, "created": time.time()}
        S["queue"].append(jid)
        S["cv"].notify_all()
    return _wait(jid, WAIT)


JOB_RESULT = {"name": "job_result", "description": "Get the output of a PC job that was still running when its tool call returned (id from that message). wait_s: how long to wait for it now (max 50).",
              "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "wait_s": {"type": "number"}}, "required": ["id"]}}


def _rpc(m):
    mid, method, params = m.get("id"), m.get("method"), m.get("params") or {}
    if mid is None:
        return None                                  # a notification - nothing to answer
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion") or "2025-03-26", "capabilities": {"tools": {"listChanged": False}},
               "serverInfo": {"name": "Michael PC Link", "version": "1.0.0"},
               "instructions": "Full access to Michael Kaspersen's Windows PC: PowerShell, files, search, screenshots, mouse and keyboard. Paths are Windows paths. Long commands keep running; fetch them with job_result."}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": list(S["tools"]) + [JOB_RESULT]}
    elif method == "tools/call":
        try:
            res = _call(str(params.get("name", "")), params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
        except Exception as e:
            res = _text(f"{type(e).__name__}: {e}", True)
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def _allowed(h, path):
    ip = (h.headers.get("X-Forwarded-For") or h.client_address[0]).split(",")[0].strip()
    f = [t for t in S["fails"].get(ip, []) if t > time.time() - 600]
    if len(f) >= 8:
        return False
    tok = path.split("/mcp/", 1)[1].strip("/") if "/mcp/" in path else ""
    want = _token_hash()
    if len(tok) >= 32 and want and hmac.compare_digest(hashlib.sha256(tok.encode()).hexdigest(), want):
        return True
    S["fails"][ip] = f + [time.time()]
    return False


def handle_mcp(h, path, d):
    if not _allowed(h, path):
        return h.sendj({"error": "Not found"}, 404)
    msgs = d if isinstance(d, list) else [d]
    out = [r for r in (_rpc(m) for m in msgs if isinstance(m, dict)) if r is not None]
    if not out:
        h.send_response(202); h.send_header("Content-Length", "0"); h.end_headers(); return
    body = json.dumps(out if isinstance(d, list) else out[0]).encode()
    h.send_response(200); h.send_header("Content-Type", "application/json"); h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store"); h.end_headers(); h.wfile.write(body)


def handle_get(h, path):
    # no server-initiated stream: the spec says answer 405 and the client carries on with plain POSTs
    h.send_response(405 if _allowed(h, path) else 404); h.send_header("Allow", "POST"); h.send_header("Content-Length", "0"); h.end_headers()
