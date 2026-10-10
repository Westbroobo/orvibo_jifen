"""Isolated launcher tests: no database, credentials, or Feishu requests."""

import ctypes
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("start_local", Path(__file__).with_name("start-local.py"))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def alive(pid):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="jifen-launcher-")
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.marker = self.root / "pids.json"
        self.service = [sys.executable, "-c", (
            "import subprocess,sys,time,json,os,pathlib; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
            "pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid])); "
            "time.sleep(120)"
        ), str(self.marker)]

    def wait_started(self, runner=None):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.marker.exists():
                try:
                    return json.loads(self.marker.read_text())
                except json.JSONDecodeError:
                    pass
            if runner and runner.poll() is not None:
                self.fail("Supervisor exited before the fake service started")
            time.sleep(0.05)
        self.fail("Fake service did not start")

    def assert_stopped(self, pids):
        self.assertTrue(all(not alive(pid) for pid in pids), f"Processes still running: {pids}")

    def test_service_failure_stops_other_service_and_descendant(self):
        fail = [sys.executable, "-c", (
            "import pathlib,sys,time; marker=pathlib.Path(sys.argv[1]); "
            "deadline=time.monotonic()+10\n"
            "while not marker.exists() and time.monotonic()<deadline: time.sleep(.05)\n"
            "sys.exit(7)"
        ), str(self.marker)]
        with self.assertRaisesRegex(RuntimeError, "退出码 7"):
            launcher.supervise([("worker", self.service, self.root), ("API", fail, self.root)], dict(os.environ))
        self.assert_stopped(self.wait_started())

    def test_terminal_interrupt_stops_entire_tree(self):
        # Exercise a real console control event against a separate supervisor.
        script = (
            "import runpy,sys,signal,os,pathlib; "
            "module=runpy.run_path(sys.argv[1]); "
            "signal.signal(signal.SIGBREAK if os.name=='nt' else signal.SIGINT,signal.default_int_handler)\n"
            "try: module['supervise']([('worker',sys.argv[3:],pathlib.Path(sys.argv[2]))],dict(os.environ))\n"
            "except KeyboardInterrupt: pass"
        )
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        runner = subprocess.Popen([sys.executable, "-c", script, str(Path(launcher.__file__)), str(self.root), *self.service], **options)
        try:
            pids = self.wait_started(runner)
            runner.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            self.assertEqual(runner.wait(timeout=10), 0)
            self.assert_stopped(pids)
        finally:
            launcher.stop_processes([runner])

    def test_occupied_port_fails_without_touching_listener(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaisesRegex(RuntimeError, "已被占用"):
                launcher.check_ports([listener.getsockname()[1]])
            self.assertGreaterEqual(listener.fileno(), 0)

    def test_frontend_starts_only_after_api_health_is_ready(self):
        ready = self.root / "api-ready"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        api = [sys.executable, "-c", (
            "import http.server,pathlib,sys,time\n"
            "class Handler(http.server.BaseHTTPRequestHandler):\n"
            " def do_GET(self):\n"
            "  pathlib.Path(sys.argv[2]).write_text('ready')\n"
            "  self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
            " def log_message(self,*args): pass\n"
            "time.sleep(.5)\n"
            "http.server.HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()"
        ), str(port), str(ready)]
        frontend = [sys.executable, "-c", (
            "import pathlib,sys; sys.exit(7 if pathlib.Path(sys.argv[1]).exists() else 9)"
        ), str(ready)]
        processes = []
        original_spawn = launcher.spawn

        def capture_spawn(*args):
            process = original_spawn(*args)
            processes.append(process)
            return process

        with patch.object(launcher, "spawn", side_effect=capture_spawn):
            with self.assertRaisesRegex(RuntimeError, "退出码 7"):
                launcher.supervise([("API", api, self.root), ("前端", frontend, self.root)], dict(os.environ),
                                   startup_checks={"API": f"http://127.0.0.1:{port}/api/health"}, timeout=5)
        self.assert_stopped([p.pid for p in processes])

    def test_configured_port_and_host_reach_frontend_backend_and_health_check(self):
        (self.root / ".env").touch()
        for url, port in (("http://localhost:5174", 5174), ("http://127.0.0.1:6100", 6100)):
            with self.subTest(url=url), \
                    patch.object(launcher, "ROOT", self.root), \
                    patch.object(launcher, "check_ports") as check_ports, \
                    patch.object(launcher, "prepare_dependencies", return_value=(sys.executable, "node")), \
                    patch.object(launcher, "read_local_addresses", return_value={"public_url": url, "redirect_uri": url + "/api/auth/callback"}), \
                    patch.object(launcher, "run_step") as run_step, \
                    patch.object(launcher, "supervise") as supervise, \
                    patch.object(sys, "argv", ["start-local.py"]):
                self.assertEqual(launcher.main(), 0)
                self.assertEqual(check_ports.call_args.args[0], [port, 8000])
                run_step.assert_not_called()
                services, env, health_url, message = supervise.call_args.args
                frontend = next(command for name, command, _ in services if name == "前端")
                self.assertEqual(frontend[frontend.index("--port") + 1], str(port))
                self.assertEqual(env["PUBLIC_URL"], url)
                self.assertEqual(env["FEISHU_REDIRECT_URI"], url + "/api/auth/callback")
                self.assertEqual(health_url, f"http://127.0.0.1:{port}/api/health")
                self.assertIn(url, message)
                self.assertEqual(supervise.call_args.kwargs["startup_checks"], {"API": "http://127.0.0.1:8000/api/health"})

    def test_explicit_port_override_preserves_configured_host(self):
        result = launcher.resolve_local_addresses({
            "public_url": "http://127.0.0.1:5174", "redirect_uri": "http://127.0.0.1:5174/api/auth/callback",
        }, 5175)
        self.assertEqual(result, (5175, "http://127.0.0.1:5175", "http://127.0.0.1:5175/api/auth/callback"))

    def test_callback_mismatch_requires_fix_instead_of_silent_override(self):
        with self.assertRaisesRegex(RuntimeError, "FEISHU_REDIRECT_URI"):
            launcher.resolve_local_addresses({
                "public_url": "http://localhost:5174", "redirect_uri": "http://localhost:5173/api/auth/callback",
            })


if __name__ == "__main__":
    unittest.main()
