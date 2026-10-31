"""Independent NDJSON ACP peer for transport and CLI tests; no SDK imports."""

import json
import os
import sys


mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
trace = sys.argv[2] if len(sys.argv) > 2 else None
authenticated = False
pending = None


def send(message):
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


def reply(request, result):
    send({"id": request["id"], "result": result})


def update(session, update_type, **kwargs):
    send(
        {
            "method": "session/update",
            "params": {
                "sessionId": session,
                "update": {"sessionUpdate": update_type, **kwargs},
            },
        }
    )


for line in sys.stdin:
    request = json.loads(line)
    if trace:
        with open(trace, "a", encoding="utf-8") as output:
            output.write(json.dumps({"pid": os.getpid(), **request}) + "\n")
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialize":
        if mode == "exit":
            sys.exit(7)
        if mode == "hang-init":
            continue
        if mode == "malformed":
            reply(request, {"unexpected": True})
            continue
        print("fake agent diagnostic", file=sys.stderr, flush=True)
        reply(
            request,
            {
                "protocolVersion": 99 if mode == "incompatible" else 1,
                "agentInfo": {"name": "fake-acp", "version": "1.0"},
                "agentCapabilities": {"loadSession": mode != "no-load"},
                "authMethods": [
                    {"id": "test-login", "name": "Test login", "description": "Test"}
                ],
            },
        )
    elif method == "authenticate":
        if mode == "auth-fail":
            send(
                {
                    "id": request["id"],
                    "error": {"code": -32603, "message": "secret diagnostic"},
                }
            )
        else:
            authenticated = True
            reply(request, {})
    elif method == "session/new":
        if mode == "auth" and not authenticated:
            send(
                {
                    "id": request["id"],
                    "error": {"code": -32000, "message": "Authentication required"},
                }
            )
        else:
            reply(request, {"sessionId": "test-session"})
    elif method == "session/load":
        update(
            params["sessionId"],
            "agent_message_chunk",
            content={"type": "text", "text": "previous turn"},
        )
        reply(request, {})
    elif method == "session/prompt":
        if mode == "exit-prompt":
            sys.exit(7)
        pending = request
        session = params["sessionId"]
        update(
            "another-session",
            "agent_message_chunk",
            content={"type": "text", "text": "wrong session"},
        )
        if mode == "permission":
            send(
                {
                    "id": "permission-1",
                    "method": "session/request_permission",
                    "params": {
                        "sessionId": session,
                        "toolCall": {
                            "toolCallId": "edit-1",
                            "title": "Edit file",
                            "kind": "edit",
                        },
                        "options": [
                            {"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                            {"optionId": "no", "name": "Reject", "kind": "reject_once"},
                        ],
                    },
                }
            )
        elif mode not in {"wait", "ignore-cancel"}:
            update(
                session,
                "agent_thought_chunk",
                content={"type": "text", "text": "thinking"},
            )
            update(
                session,
                "tool_call",
                toolCallId="tool-1",
                title="Inspect",
                kind="read",
                status="in_progress",
            )
            for chunk in ["你好，", "ACP"]:
                update(
                    session,
                    "agent_message_chunk",
                    content={"type": "text", "text": chunk},
                )
            update(session, "tool_call_update", toolCallId="tool-1", status="completed")
            stop_reason = (
                mode if mode in {"refusal", "max_tokens", "cancelled"} else "end_turn"
            )
            reply(request, {"stopReason": stop_reason})
            pending = None
    elif method == "session/cancel" and pending and mode != "ignore-cancel":
        reply(pending, {"stopReason": "cancelled"})
        pending = None
    elif request.get("id") == "permission-1":
        update(
            pending["params"]["sessionId"],
            "agent_message_chunk",
            content={
                "type": "text",
                "text": json.dumps(request["result"]["outcome"]),
            },
        )
        reply(pending, {"stopReason": "end_turn"})
        pending = None
