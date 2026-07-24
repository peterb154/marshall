"""Static server for the kneeboard pages that refuses to be cached.

OpenKneeboard's embedded Chromium caches aggressively. Without these headers an
edit appears to have no effect and you end up debugging a page you are no longer
serving -- which is exactly what happened.

    uv run python serve.py [port]
"""

import functools
import http.server
import socketserver
import sys
from pathlib import Path

from marshall import config

ROOT = config.KNEEBOARD_OUT
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8362


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control",
                         "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")


class Threaded(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """One thread per connection.

    The single-threaded TCPServer wedges completely: Chromium holds a keep-alive
    connection open, the server blocks waiting on it, and every later request
    hangs. OpenKneeboard then shows "No Pages" because the page never loaded --
    which looks exactly like a page-API failure and sent us chasing one.
    """
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    handler = functools.partial(NoCache, directory=str(ROOT))
    print(f"serving {ROOT} on http://localhost:{PORT}/  (no-cache, threaded)")
    with Threaded(("0.0.0.0", PORT), handler) as srv:
        srv.serve_forever()
