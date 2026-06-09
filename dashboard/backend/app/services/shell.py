"""Safe command execution with a strict allowlist.

Privileged firewall/network operations run through this module so that the
rest of the codebase never builds shell strings dynamically. Only binaries on
the allowlist may be invoked, and arguments are always passed as a list
(never via a shell), eliminating shell-injection risk.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

# Absolute paths or resolvable binary names permitted to run.
ALLOWED_BINARIES = {
    "nft",
    "systemctl",
    "systemd-analyze",
    "ip",
    "sysctl",
    "ping",
    "ss",
    "dig",
    "dnsmasq",
    "netplan",
    "df",
    "free",
    "uptime",
    "wg",
    "wg-quick",
    "qrencode",
    "openvpn",
    "/usr/share/easy-rsa/easyrsa",
    "openfortivpn",
    "/usr/bin/openfortivpn",
    "/opt/mundix360/scripts/active-response/block-ip.sh",
    "/usr/sbin/nft",
    "/bin/systemctl",
}


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandNotAllowed(Exception):
    pass


def _is_allowed(binary: str) -> bool:
    if binary in ALLOWED_BINARIES:
        return True
    resolved = shutil.which(binary)
    if resolved and resolved in ALLOWED_BINARIES:
        return True
    return False


def run(args: list[str], timeout: int = 20, check: bool = False,
        input_text: str | None = None) -> CommandResult:
    if not args:
        raise CommandNotAllowed("empty command")
    binary = args[0]
    if not _is_allowed(binary):
        raise CommandNotAllowed(f"binary not allowed: {binary}")
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            input=input_text,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=124, stdout="", stderr="timeout")
    except FileNotFoundError:
        return CommandResult(returncode=127, stdout="", stderr=f"not found: {binary}")
    result = CommandResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if check and not result.ok:
        raise RuntimeError(f"command failed ({result.returncode}): {result.stderr.strip()}")
    return result
