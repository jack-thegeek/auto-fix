"""Deliver reports to Weixin through the Hermes messaging gateway."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from nginx_perf_agent.config import Settings
from nginx_perf_agent.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Delivery:
    """Outcome of one gateway send."""

    target: str
    ok: bool
    detail: str


def send_text(text: str, settings: Settings, target: str | None = None) -> Delivery:
    """Send `text` as a Weixin message. Long text is chunked by the gateway."""
    destination = target or settings.weixin_target
    command = [settings.hermes_bin, "send", "--to", destination, "--file", "-"]
    try:
        completed = subprocess.run(
            command,
            input=text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=settings.hermes_timeout,
            check=False,
        )
    except FileNotFoundError:
        return _failed(destination, f"hermes not found: {settings.hermes_bin}")
    except subprocess.TimeoutExpired:
        return _failed(
            destination, f"timed out after {settings.hermes_timeout:g}s"
        )
    except OSError as exc:
        return _failed(destination, str(exc))

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        return _failed(destination, detail or f"exit code {completed.returncode}")

    # shortcut: the Weixin adapter splits messages at 2000 chars; split here
    # only if a gateway stops chunking.
    log.info("weixin_report_sent", target=destination, chars=len(text))
    return Delivery(destination, True, f"{len(text)} chars")


def _failed(target: str, detail: str) -> Delivery:
    log.error("weixin_report_failed", target=target, error=detail)
    return Delivery(target, False, detail)
