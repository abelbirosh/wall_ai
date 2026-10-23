"""mitmproxy add-on: log every outbound call from the target and mock its response.

Only hosts in WALLAI_ALLOW_HOSTS reach the network. Logs host, method and path only:
no query strings, headers or bodies, since those can carry credentials.
"""

import json
import os
import threading
import time

from mitmproxy import http

LOG = os.environ["WALLAI_EGRESS_LOG"]
ALLOW = {h for h in os.environ.get("WALLAI_ALLOW_HOSTS", "").split(",") if h}
_lock = threading.Lock()


def _log(record: dict) -> None:
    record["time"] = round(time.time(), 3)
    with _lock, open(LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


class Egress:
    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        allowed = host in ALLOW
        _log(
            {
                "host": host,
                "method": flow.request.method,
                "path": flow.request.path.split("?", 1)[0],
                "action": "allowed" if allowed else "mocked",
            }
        )
        if not allowed:
            flow.response = http.Response.make(200, b"{}", {"Content-Type": "application/json"})

    def tls_failed_client(self, data) -> None:
        # The target didn't trust the proxy's CA, so the call never got as far as a request.
        _log({"host": data.context.client.sni, "action": "tls_failed"})


addons = [Egress()]
