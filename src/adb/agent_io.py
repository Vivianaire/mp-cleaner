"""PC ↔ mp-cleaner agent(Shizuku)通信:adb forward + socket + JSON 协议。

agent app 在手机 Shizuku 进程(uid 2000)开 TCP server(localhost:27042);PC 经
``adb forward tcp:27042 tcp:27042`` 把本机 27042 转发到设备,连入 agent。

协议:一行 JSON 请求 ``{"cmd","args"}``;响应——单行 JSON(普通命令)或 NDJSON 流
(scan:多行 ``{"r":"record"}`` + 末行 ``{"end":true}``)。

任何 agent 故障(未装/未授权/服务未起/转发/连接失败)抛 ``AgentUnavailable``;
调用方(`ShizukuAgentBackend`/main_window)据此回退 ``AdbShellBackend``。
"""
from __future__ import annotations

import json
import socket
from typing import Iterator

from .client import AdbClient

AGENT_PORT = 27042
AGENT_PKG = "com.mpcleaner.agent"


class AgentUnavailable(RuntimeError):
    """agent 不可用。调用方应回退 AdbShellBackend。"""


class AgentClient:
    """与 agent 的短连接客户端:每次请求新建 socket(agent server 每连接处理一请求)。"""

    def __init__(self, client: AdbClient, serial: str):
        self._client = client
        self._serial = serial
        self._forwarded = False

    def forward(self) -> None:
        """adb forward tcp:27042 tcp:27042(本地端口 → 设备 agent 端口)。幂等。"""
        if self._forwarded:
            return
        try:
            self._client._run(  # noqa: SLF001
                ["-s", self._serial, "forward", f"tcp:{AGENT_PORT}", f"tcp:{AGENT_PORT}"]
            )
            self._forwarded = True
        except Exception as e:  # noqa: BLE001
            raise AgentUnavailable(f"adb forward 失败:{e}") from e

    def _connect(self, timeout: float = 5.0) -> socket.socket:
        try:
            s = socket.create_connection(("127.0.0.1", AGENT_PORT), timeout=timeout)
            return s
        except OSError as e:
            raise AgentUnavailable(f"连接 agent 端口 {AGENT_PORT} 失败:{e}") from e

    def _request(self, cmd: str, args: dict) -> socket.socket:
        s = self._connect()
        s.sendall(
            (json.dumps({"cmd": cmd, "args": args}, ensure_ascii=False) + "\n").encode("utf-8")
        )
        return s

    def ping(self) -> bool:
        try:
            s = self._request("ping", {})
            try:
                return bool(self._read_line(s).get("ok"))
            finally:
                s.close()
        except Exception:  # noqa: BLE001
            return False

    def send(self, cmd: str, **args) -> dict:
        """单请求/单响应(普通命令)。返回响应 JSON dict。"""
        s = self._request(cmd, args)
        try:
            return self._read_line(s)
        finally:
            s.close()

    def stream(self, cmd: str, **args) -> Iterator[str]:
        """流式(scan):逐行读 NDJSON,yield record 字符串,遇 end 停。"""
        s = self._request(cmd, args)
        try:
            f = s.makefile("r", encoding="utf-8", errors="replace", newline="\n")
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("end"):
                    return
                if obj.get("error"):
                    raise AgentUnavailable(str(obj["error"]))
                if "r" in obj:
                    yield str(obj["r"])
        finally:
            s.close()

    @staticmethod
    def _read_line(s: socket.socket) -> dict:
        f = s.makefile("r", encoding="utf-8", errors="replace", newline="\n")
        line = f.readline()
        if not line:
            raise AgentUnavailable("agent 无响应")
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            raise AgentUnavailable(f"agent 响应解析失败:{line.strip()!r}") from e
