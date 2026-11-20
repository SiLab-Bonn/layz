"""layz's log: every line of every tool a flow runs, on the terminal, one line each:

    13:38:17 INFO  [gdscheck]  Report written to: results/route_demo/drc/drc.lyrdb
    13:38:18 WARN  [layz]      net label 'X' at (10.0, 4.0) µm lies on no M3 copper
    13:38:20 ERROR [hyperlynx] Simulation failed due to the following reason: ...

The level is the tool's own when it gives one ([INFO], WARNING:, Error ...), else read from
the words (error, fail, fatal, traceback: ERROR; warn: WARN), else INFO. Colours on a terminal
(NO_COLOR turns them off). External tools run through ``run``, which also writes their output
to a log file when given one; layz's own prints, inside a flow's targets, through ``capture``.
A flow's run also goes to results/<design>/run.log (``FILE``), which `layz web` shows per target.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RESET, DIM = "\033[0m", "\033[2m"
COLOURS = {"INFO": "\033[32m", "WARN": "\033[33m", "ERROR": "\033[31m"}  # green, yellow, red
TOOL_COLOUR = "\033[36m"  # cyan
_TAG = re.compile(r"^\s*\[?(INFO|INFORMATION|NOTE|WARN|WARNING|ERROR|FATAL|CRITICAL)\]?[:\s]\s*", re.I)
_ERROR = re.compile(r"\b(error|errors|fail|failed|failure|fatal|traceback|exception)\b", re.I)
_WARN = re.compile(r"\b(warn|warning|warnings)\b", re.I)
_REAL: list = []  # the stdout capture() replaced: where the log goes meanwhile
COUNTS: dict = {"INFO": 0, "WARN": 0, "ERROR": 0, "fail": 0}  # this step's lines per level, failed checks
FILE: dict = {"file": None, "lines": 0}  # a copy of the log, plain (layz.flow: results/<design>/run.log)


def _out():
    return _REAL[-1] if _REAL else sys.stdout


def _colour() -> bool:
    out = _out()
    return hasattr(out, "isatty") and out.isatty() and "NO_COLOR" not in os.environ


def level_of(line: str) -> tuple[str, str]:
    """The level of a line, and the line without the tool's own level tag."""
    m = _TAG.match(line)
    if m:
        tag = m[1].upper()
        level = "ERROR" if tag in ("ERROR", "FATAL", "CRITICAL") else "WARN" if tag.startswith("WARN") else "INFO"
        return level, line[m.end() :]
    if _ERROR.search(line) and not re.search(r"\b0 (errors|violations)\b|\b(relative|estimated|max|maximum|tolerance|approximation)\s+error", line, re.I):
        return "ERROR", line
    if _WARN.search(line):
        return "WARN", line
    return "INFO", line


def emit(tool: str, line: str, level: str | None = None) -> None:
    line = line.rstrip("\n")
    if not line.strip():
        return
    if level is None:
        level, line = level_of(line)
    if tool != "flow":
        COUNTS[level] += 1
    stamp = time.strftime("%H:%M:%S")
    tag = f"[{tool}]"
    out = _out()
    if FILE["file"] is not None:
        FILE["file"].write(f"{stamp} {level:<5} {tag:<12} {line}\n")
        FILE["file"].flush()
        FILE["lines"] += 1
    if _colour():
        out.write(f"{DIM}{stamp}{RESET} {COLOURS[level]}{level:<5}{RESET} {TOOL_COLOUR}{tag:<12}{RESET} {line}\n")
    else:
        out.write(f"{stamp} {level:<5} {tag:<12} {line}\n")
    out.flush()


def info(tool: str, line: str) -> None:
    emit(tool, line, "INFO")


def warn(tool: str, line: str) -> None:
    emit(tool, line, "WARN")


def error(tool: str, line: str) -> None:
    emit(tool, line, "ERROR")


def run(tool: str, cmd: list[str], *, cwd: Path | None = None, env: dict | None = None, log: Path | None = None, stdin=subprocess.DEVNULL) -> int:
    """Run an external tool, every line of its output to the log as ``[tool]`` (and into ``log``);
    its exit code."""
    file = open(log, "w") if log else None  # noqa: SIM115
    try:
        proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        for line in proc.stdout:
            if file:
                file.write(line)
            emit(tool, line)
        return proc.wait()
    finally:
        if file:
            file.close()


class _Lines:
    """A stream that sends each line written to it to the log, as ``tool``."""

    def __init__(self, tool: str, level: str | None = None):
        self.tool, self.level, self.buf = tool, level, ""

    def write(self, text: str) -> int:
        self.buf += text
        *lines, self.buf = self.buf.split("\n")
        for line in lines:
            emit(self.tool, line, self.level if self.level and level_of(line)[0] == "INFO" else None)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    def close(self) -> None:
        if self.buf:
            emit(self.tool, self.buf, self.level)
            self.buf = ""


@contextlib.contextmanager
def capture(tool: str = "layz"):
    """layz's own prints (and warnings on stderr, at least WARN) go to the log as ``tool``."""
    out, err = _Lines(tool), _Lines(tool, "WARN")
    old = sys.stdout, sys.stderr
    _REAL.append(sys.stdout)
    sys.stdout, sys.stderr = out, err
    try:
        yield
    finally:
        out.close()
        err.close()
        sys.stdout, sys.stderr = old
        _REAL.pop()
