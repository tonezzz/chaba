#!/usr/bin/env python3
"""ssh_route.py — resilient fleet-ssh runner for the tailnet mesh.

A controller's ~/.ssh/config can carry a ProxyJump/ProxyCommand that a
hardened jump host refuses: the 2026-11-26 scoped-sftp policy set
`AllowTcpForwarding no` fleet-wide, so tony-dell's stale
`Host idc03 -> ProxyJump tony-omen` dies with `channel 0: open failed:
administratively prohibited` while direct tailnet ssh works fine
(card runner-drift-rearm-idc03-ssh-proxyjump-dead; same class fixed in
mcp-health execOnHealthHost 2026-11-26).

The declared mesh route is direct tailnet (ansible_host = tailnet IP in
ansible/inventory), so ssh_run() tries `ProxyJump=none ProxyCommand=none`
first — the alias still resolves HostName/User/IdentityFile from the
stanza — then falls back to the operator's ssh config. A genuinely
needed jump still works via the fallback; a dead one can no longer
wedge the caller into a silent no-op.

Import:  sys.path.insert(0, "<repo>/scripts/lib"); from ssh_route import ssh_run
"""
from __future__ import annotations

import subprocess

# ssh options every fleet probe shares; callers append their own
# (ConnectTimeout etc.) via `opts`.
BASE_OPTS = ["-o", "BatchMode=yes"]

# Direct-tailnet attempt first, then the operator's ssh config as-is.
# Matches mcp-servers/mcp-health/server.js execOnHealthHost ordering.
_DIRECT_OPTS = ["-o", "ProxyJump=none", "-o", "ProxyCommand=none"]


def ssh_argvs(target, remote, opts=BASE_OPTS):
    """Yield full ssh argv candidates for `ssh <target> <remote>`.

    ``remote`` is a shell string or a list of argv elements (joined by
    the remote shell either way, so a leading ``~`` still expands).
    """
    remote_args = [remote] if isinstance(remote, str) else list(remote)
    for extra in (_DIRECT_OPTS, []):
        yield ["ssh", *opts, *extra, target, *remote_args]


def ssh_run(target, remote, *, opts=BASE_OPTS, input=None,
            capture_output=True, text=False, timeout=60):
    """Run ``ssh <opts> <target> <remote>`` over the route chain.

    Returns the CompletedProcess of the first route that exits 0. When
    every route fails, returns the LAST route's result — the
    operator-config attempt, whose stderr is the most meaningful error
    for the caller's existing rc/stderr handling. A TimeoutExpired on
    the last route propagates so callers keep their timeout semantics;
    a timeout on an earlier route just advances to the next route.
    """
    last_res = None
    last_exc = None
    for argv in ssh_argvs(target, remote, opts):
        try:
            res = subprocess.run(argv, input=input,
                                 capture_output=capture_output, text=text,
                                 timeout=timeout)
        except subprocess.TimeoutExpired as e:
            last_res, last_exc = None, e
            continue
        if res.returncode == 0:
            return res
        last_res, last_exc = res, None
    if last_exc is not None:
        raise last_exc
    return last_res
