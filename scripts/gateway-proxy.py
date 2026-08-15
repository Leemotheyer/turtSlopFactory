#!/usr/bin/env python3
"""Minimal Caddy-like gateway for local repro: :8044 -> API :8000 / dashboard :3000."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import sys

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8044
API_HOST = "127.0.0.1"
API_PORT = 8000
DASH_HOST = "127.0.0.1"
DASH_PORT = 3000


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self, host: str, port: int) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None
        path = self.path
        conn = http.client.HTTPConnection(host, port, timeout=60)
        headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}
        headers["Host"] = f"{host}:{port}"
        headers["X-Forwarded-Host"] = self.headers.get("Host", f"127.0.0.1:{LISTEN_PORT}")
        headers["X-Forwarded-Proto"] = "http"
        headers["X-Real-IP"] = self.client_address[0]
        headers["X-Forwarded-For"] = self.client_address[0]
        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status, resp.reason)
            for key, value in resp.getheaders():
                if key.lower() == "transfer-encoding":
                    continue
                self.send_header(key, value)
            self.end_headers()
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        finally:
            conn.close()

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def do_PUT(self):
        self._route()

    def do_DELETE(self):
        self._route()

    def do_OPTIONS(self):
        self._route()

    def _route(self) -> None:
        if self.path.startswith(
            ("/api/", "/health", "/docs", "/openapi.json", "/redoc", "/ws/", "/preview/")
        ):
            self._proxy(API_HOST, API_PORT)
        else:
            self._proxy(DASH_HOST, DASH_PORT)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), GatewayHandler)
    print(f"Gateway listening on :{LISTEN_PORT}", flush=True)
    server.serve_forever()
