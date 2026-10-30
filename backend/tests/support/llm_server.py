"""Scripted OpenAI-compatible server for tests (no model, no network access, never used in production).

    python -m tests.support.llm_server --host 0.0.0.0 --port 8080

POST /v1/chat/completions answers like a small, obedient model:
- by default it extracts what is plainly written in the email (catalogue names, student numbers such as
  D130000001, academic years such as 2026-2027, "N exemplaires") and quotes the text it used;
- directives in the email simulate failures or a compromised model:
    [[llm:timeout]]      answers after 30 s (the client times out first)
    [[llm:500]]          HTTP 500 (provider unavailable)
    [[llm:redirect]]     HTTP 307 to another host (must not be followed)
    [[llm:invalid]]      non-JSON answer
    [[llm:tool]]         a tool call (must be refused)
    [[llm:obey]]         returns the JSON object written in the email, as is (prompt injection succeeded)
    [[llm:hallucinate]]  invents a student number and a document code absent from the email / catalogue
GET /_requests returns every request received (to prove what was, and was not, sent); DELETE clears it.
"""

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_lock = threading.Lock()
RECEIVED: list[dict] = []

_EMAIL_RE = re.compile(r"<<<EMAIL_([0-9a-f]+)>>>\n(.*)\n<<<END_\1>>>", re.DOTALL)
_CATALOGUE_RE = re.compile(r"^- ([A-Za-z0-9_\-]+): (.+)$", re.MULTILINE)
_NUMBER_RE = re.compile(r"\b[A-Z]\d{9}\b")
_YEAR_RE = re.compile(r"\b\d{4}-\d{4}\b")
_QTY_RE = re.compile(r"\b(\d{1,2})\s+(exemplaires?|copies?)\b", re.IGNORECASE)


def _line_of(text: str, start: int) -> str:
    begin = text.rfind("\n", 0, start) + 1
    end = text.find("\n", start)
    return text[begin : end if end != -1 else len(text)].strip()[:300]


def extract(system: str, email: str) -> dict:
    lowered = email.casefold()
    documents = []
    for code, names in _CATALOGUE_RE.findall(system):
        for name in [n.strip() for n in names.split(" / ") if n.strip()]:
            pos = lowered.find(name.casefold())
            if pos != -1:
                quote = _line_of(email, pos)
                qty = _QTY_RE.search(quote)
                documents.append(
                    {
                        "document_type_code": code,
                        "quantity": int(qty.group(1)) if qty else None,
                        "quote": quote,
                    }
                )
                break
    out: dict = {
        "is_document_request": bool(documents),
        "requested_documents": documents[:10],
        "missing_information": [] if documents else ["document_type"],
        "suspicious_content": "ignore" in lowered and "instruction" in lowered,
        "self_reported_confidence": 0.9,
        "language": "fr",
    }
    if m := _NUMBER_RE.search(email):
        out["student_number"] = {"value": m.group(0), "quote": _line_of(email, m.start())}
    if m := _YEAR_RE.search(email):
        out["academic_year_label"] = {"value": m.group(0), "quote": _line_of(email, m.start())}
    return out


def _completion(content: str | None, *, tool: bool = False) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool:
        message["tool_calls"] = [
            {"id": "call_1", "type": "function", "function": {"name": "create_request", "arguments": "{}"}}
        ]
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "studentdocs-test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool else "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # quiet
        pass

    def _send(self, status: int, body: dict | str) -> None:
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/_health":
            self._send(200, {"status": "ok"})
        elif self.path == "/_requests":
            with _lock:
                self._send(200, list(RECEIVED))
        else:
            self._send(404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path == "/_requests":
            with _lock:
                RECEIVED.clear()
            self._send(204, "")
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "bad json"})
            return
        with _lock:
            RECEIVED.append({"path": self.path, "host": self.headers.get("Host"), "body": payload})
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": "not found"})
            return
        messages = payload.get("messages") or []
        system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        match = _EMAIL_RE.search(user)
        email = match.group(2) if match else ""

        if "[[llm:timeout]]" in email:
            time.sleep(30)
            self._send(200, _completion("{}"))
        elif "[[llm:redirect]]" in email:
            self.send_response(307)
            self.send_header("Location", "http://exfiltration.invalid/v1/chat/completions")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif "[[llm:500]]" in email:
            self._send(500, {"error": "overloaded"})
        elif "[[llm:invalid]]" in email:
            self._send(200, _completion("Sure! Here is what I found: the student wants a document."))
        elif "[[llm:tool]]" in email:
            self._send(200, _completion(None, tool=True))
        elif "[[llm:obey]]" in email:
            start, end = email.find("{"), email.rfind("}")
            self._send(200, _completion(email[start : end + 1] if start != -1 else "{}"))
        elif "[[llm:hallucinate]]" in email:
            out = extract(system, email)
            out["student_number"] = {"value": "Z999999999", "quote": "mon numéro est Z999999999"}
            out["requested_documents"].append(
                {"document_type_code": "DIPLOME_FAKE", "quantity": 1, "quote": email[:40] or "x"}
            )
            self._send(200, _completion(json.dumps(out)))
        else:
            self._send(200, _completion(json.dumps(extract(system, email), ensure_ascii=False)))


def serve(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve(args.host, args.port).serve_forever()


if __name__ == "__main__":
    main()
