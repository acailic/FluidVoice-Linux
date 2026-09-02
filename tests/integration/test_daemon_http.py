"""Real daemon subprocess: unix-socket control + settings web UI over HTTP."""
import json
import time
import urllib.request

import pytest

from fluidvoice import control
from fluidvoice import paths

pytestmark = [pytest.mark.integration]


class TestDaemonProcess:
    def test_status_and_webui(self, daemon_process):
        status = control.request("status")
        assert status["ok"] and status["recording"] is False
        assert isinstance(status["webui_port"], int) and status["webui_port"] > 0

    def test_webui_http_roundtrip(self, daemon_process):
        status = control.request("status")
        port = status["webui_port"]
        # page
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert b"FluidVoice" in r.read()
        # API with a same-origin-shaped request
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/status",
            headers={"Host": f"127.0.0.1:{port}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        assert data["recording"] is False
        # the hostile request from a browser context is still rejected
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/api/config", body=b"{}",
                     headers={"Host": f"127.0.0.1:{port}",
                              "Origin": "https://evil.example",
                              "Content-Type": "application/json"})
        assert conn.getresponse().status == 403
        conn.close()

    def test_toggle_cancel_cycle(self, daemon_process):
        assert control.request("toggle")["recording"] is True
        time.sleep(0.8)
        resp = control.request("cancel")
        assert resp["cancelled"] is True and resp["recording"] is False

    def test_paste_last_reports_nothing_initially(self, daemon_process):
        resp = control.request("paste-last")
        assert resp["ok"] is False and "nothing" in (resp.get("error") or "")

    def test_shutdown_cleans_socket(self, daemon_process):
        import subprocess
        socket = paths.socket_path()
        assert socket.exists()
        daemon_process.send_signal(2)  # SIGINT -> graceful shutdown
        daemon_process.wait(timeout=10)
        deadline = time.monotonic() + 5
        while socket.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not socket.exists()

    def test_unknown_action_rejected(self, daemon_process):
        resp = control.request("explode")
        assert resp["ok"] is False
