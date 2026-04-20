'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 11:43:32
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 11:43:40
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\logger.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
日志工具模块 - 对应 src/logger.ts
彩色控制台日志，无第三方依赖
"""
import sys
import os
import time
from datetime import datetime

# Windows: 强制 stdout/stderr 使用 UTF-8，并启用 ANSI 转义码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    os.system("chcp 65001 >nul 2>&1")  # 切换控制台代码页到 UTF-8


# ANSI 颜色代码
COLORS = {
    "reset":   "\x1b[0m",
    "gray":    "\x1b[90m",
    "green":   "\x1b[32m",
    "yellow":  "\x1b[33m",
    "red":     "\x1b[31m",
    "cyan":    "\x1b[36m",
    "magenta": "\x1b[35m",
    "blue":    "\x1b[34m",
    "bold":    "\x1b[1m",
}


def _timestamp() -> str:
    now = datetime.now()
    h = str(now.hour).zfill(2)
    m = str(now.minute).zfill(2)
    s = str(now.second).zfill(2)
    ms = str(now.microsecond // 1000).zfill(3)
    return f"{COLORS['gray']}[{h}:{m}:{s}.{ms}]{COLORS['reset']}"


def _format_duration(ms: float) -> str:
    if ms < 1000:
        return f"{int(ms)}ms"
    return f"{ms / 1000:.1f}s"


class Logger:
    """彩色日志工具，对应 TypeScript 版 logger"""

    def info(self, tag: str, *args):
        c = COLORS
        parts = [str(a) for a in args]
        print(f"{_timestamp()} {c['cyan']}INFO {c['reset']} {c['bold']}[{tag}]{c['reset']} {' '.join(parts)}")

    def success(self, tag: str, *args):
        c = COLORS
        parts = [str(a) for a in args]
        print(f"{_timestamp()} {c['green']}✓ OK {c['reset']} {c['bold']}[{tag}]{c['reset']} {' '.join(parts)}")

    def warn(self, tag: str, *args):
        c = COLORS
        parts = [str(a) for a in args]
        print(f"{_timestamp()} {c['yellow']}WARN {c['reset']} {c['bold']}[{tag}]{c['reset']} {' '.join(parts)}")

    def error(self, tag: str, *args):
        c = COLORS
        parts = [str(a) for a in args]
        print(f"{_timestamp()} {c['red']}ERR  {c['reset']} {c['bold']}[{tag}]{c['reset']} {' '.join(parts)}")

    def ai(self, tag: str, *args):
        c = COLORS
        parts = [str(a) for a in args]
        print(f"{_timestamp()} {c['magenta']}🤖 AI {c['reset']} {c['bold']}[{tag}]{c['reset']} {' '.join(parts)}")

    def erp(self, tag: str, *args):
        c = COLORS
        parts = [str(a) for a in args]
        print(f"{_timestamp()} {c['blue']}🏭 ERP{c['reset']} {c['bold']}[{tag}]{c['reset']} {' '.join(parts)}")

    def http(self, method: str, url: str, status: int, duration_ms: float, extra: str = ""):
        c = COLORS
        status_color = c["red"] if status >= 500 else (c["yellow"] if status >= 400 else c["green"])
        dur = _format_duration(duration_ms)
        extra_str = f" {c['gray']}{extra}{c['reset']}" if extra else ""
        print(
            f"{_timestamp()} {c['gray']}HTTP {c['reset']}"
            f" {c['cyan']}{method.ljust(6)}{c['reset']}"
            f" {url.ljust(35)}"
            f" {status_color}{status}{c['reset']}"
            f" {c['gray']}{dur}{c['reset']}"
            f"{extra_str}"
        )


logger = Logger()


def start_timer():
    """计时器工厂，返回一个函数，调用后返回经过的毫秒数"""
    start = time.time()
    def elapsed() -> int:
        return int((time.time() - start) * 1000)
    return elapsed
