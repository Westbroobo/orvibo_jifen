"""Start the real local app in one terminal; Ctrl+C stops all services."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def spawn(command, cwd, env):
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(command, cwd=cwd, env=env, **options)


def stop_processes(processes):
    # Children have their own process groups, so terminal Ctrl+C reaches only
    # this supervisor. Stop entire trees, including the worker's SDK process.
    for process in reversed(processes):
        if process.poll() is not None:
            continue
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 5
    for process in processes:
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()


def run_step(command, cwd, env, label):
    print(label, flush=True)
    process = spawn(command, cwd, env)
    try:
        if process.wait() != 0:
            raise RuntimeError(f"{label}失败，请检查上方错误后重新启动。")
    finally:
        stop_processes([process])


def check_ports(ports):
    if len(set(ports)) != len(ports):
        raise RuntimeError("前端和 API 必须使用不同端口。")
    for port in ports:
        with socket.socket() as listener:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(f"端口 {port} 已被占用，请停止占用它的程序，或使用 --port / --api-port 更换端口。") from None


def prepare_dependencies(env):
    node = shutil.which("node")
    if not node:
        raise RuntimeError("请先安装 Node.js 24，再运行本命令。")
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        run_step([sys.executable, "-m", "venv", str(ROOT / ".venv")], ROOT, env, "创建 Python 环境")
    # Check the pinned dependencies without importing the application or
    # loading credentials. Existing complete environments need no install.
    probe = (
        "import importlib.metadata as m, pathlib; "
        "requirements=pathlib.Path('requirements.lock.txt').read_text().splitlines(); "
        "assert all(m.version(name)==version for name,version in "
        "(line.split('==') for line in requirements if '==' in line))"
    )
    check = subprocess.run([str(python), "-c", probe], cwd=ROOT / "backend", env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check.returncode:
        run_step([str(python), "-m", "pip", "install", "-r", "requirements.lock.txt"],
                 ROOT / "backend", env, "安装后端依赖")

    frontend = ROOT / "frontend"
    probe = subprocess.run([node, "--input-type=module", "-e", "await import('vite'); await import('@vitejs/plugin-vue'); await import('vue')"],
                           cwd=frontend, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise RuntimeError("未找到 npm，请重新安装 Node.js 24。")
        # Invoke npm's JS entry directly on Windows, avoiding shell quoting
        # problems when Node is installed under a path containing spaces.
        npm_command = [node, str(Path(npm).parent / "node_modules/npm/bin/npm-cli.js")] if os.name == "nt" else [npm]
        run_step([*npm_command, "ci"], frontend, env, "安装前端依赖")
    return str(python), node


def ensure_services_running(services, processes):
    for (name, _, _), process in zip(services, processes):
        code = process.poll()
        if code is not None:
            raise RuntimeError(f"{name} 意外退出（退出码 {code}），其余服务已停止，请检查上方错误。")


def wait_for_health(url, services, processes, timeout):
    deadline = time.monotonic() + timeout
    while True:
        ensure_services_running(services, processes)
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("启动超时，请检查上方 API 和前端错误。")
        time.sleep(0.2)


def supervise(services, env, health_url=None, ready_message="", timeout=60, startup_checks=None):
    processes = []
    try:
        for name, command, cwd in services:
            process = spawn(command, cwd, env)
            processes.append(process)
            print(f"已启动 {name}", flush=True)
            if startup_checks and name in startup_checks:
                wait_for_health(startup_checks[name], services, processes, timeout)
        if health_url:
            wait_for_health(health_url, services, processes, timeout)
        if ready_message:
            print(ready_message, flush=True)
        while True:
            ensure_services_running(services, processes)
            time.sleep(0.2)
    finally:
        stop_processes(processes)


def port_number(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 1 到 65535 之间。")
    return port


def read_local_addresses(python, env):
    # Use the backend's settings loader so dotenv syntax and configuration
    # precedence match the API. Only these two public addresses leave the child.
    probe = (
        "import json; from app.config import get_settings; s=get_settings(); "
        "print(json.dumps({'public_url': s.public_url, 'redirect_uri': s.feishu_redirect_uri}))"
    )
    result = subprocess.run([python, "-c", probe], cwd=ROOT / "backend", env=env,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("读取 .env 配置失败，请检查配置格式。")
    return json.loads(result.stdout)


def resolve_local_addresses(config, port_override=None):
    url = config["public_url"].rstrip("/")
    try:
        address = urlsplit(url)
        port = address.port or 80
    except ValueError:
        raise RuntimeError("PUBLIC_URL 的地址或端口无效。") from None
    if (address.scheme != "http" or address.hostname not in {"localhost", "127.0.0.1"}
            or address.path or address.query or address.fragment or address.username or address.password):
        raise RuntimeError("本地启动请将 PUBLIC_URL 填为 http://localhost:端口 或 http://127.0.0.1:端口。")
    if port_override is not None:
        port = port_override
        url = f"http://{address.hostname}:{port}"
        redirect_uri = f"{url}/api/auth/callback"
    else:
        redirect_uri = config["redirect_uri"]
        if redirect_uri != f"{url}/api/auth/callback":
            raise RuntimeError("FEISHU_REDIRECT_URI 须为 PUBLIC_URL 加 /api/auth/callback，请检查 .env。")
    return port, url, redirect_uri


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="一行命令启动 ORVIBO_员工积分系统；Ctrl+C 停止全部服务。")
    parser.add_argument("--port", type=port_number, help="临时覆盖前端端口，默认读取 .env 的 PUBLIC_URL")
    parser.add_argument("--api-port", type=port_number, default=8000, help="API 端口，默认 8000")
    args = parser.parse_args()
    # CTRL_BREAK also supports shutting down this supervisor from a parent
    # terminal or another local development tool on Windows.
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    try:
        if sys.version_info < (3, 13):
            raise RuntimeError("请使用 Python 3.13：py -3.13 scripts\\start-local.py")
        if not (ROOT / ".env").is_file():
            raise RuntimeError("请先将 .env.example 复制为 .env，填写数据库、飞书和初始管理员配置。")
        env = {**os.environ, "APP_ENV": "development", "COOKIE_SECURE": "false", "DEMO_MODE": "false",
               "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "DEV_API_PORT": str(args.api_port)}
        python, node = prepare_dependencies(env)
        port, url, redirect_uri = resolve_local_addresses(read_local_addresses(python, env), args.port)
        env.update(PUBLIC_URL=url, FEISHU_REDIRECT_URI=redirect_uri)
        check_ports([port, args.api_port])
        services = [
            ("API", [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.api_port), "--no-access-log"], ROOT / "backend"),
            ("worker", [python, "-m", "app.worker"], ROOT / "backend"),
            ("前端", [node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(port), "--strictPort"], ROOT / "frontend"),
        ]
        supervise(services, env, f"http://127.0.0.1:{port}/api/health",
                  f"\nORVIBO_员工积分系统：{url}\n飞书登录回调：{redirect_uri}\n按 Ctrl+C 停止全部服务。\n",
                  startup_checks={"API": f"http://127.0.0.1:{args.api_port}/api/health"})
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
        return 0
    except (RuntimeError, OSError) as error:
        print(f"\n启动失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
