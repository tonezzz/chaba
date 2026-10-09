#!/usr/bin/env python3
"""Apply or verify the staging actuation-guard overlay on a cloned HA config.

The overlay policy lives in
    docs/ssot/infrastructure/ssot.home-assistant.staging-overlay.yml
so the strip/stub list stays reviewable. This script is driven by it.

Usage:
    staging-overlay.py apply  --config DIR [--overlay PATH] [--instance ID]
                              [--set-key name="Tony DEV"] [--dry-run]
    staging-overlay.py verify --config DIR [--overlay PATH] [--instance ID]
    staging-overlay.py audit  --config DIR   (dry-run apply, no writes)

Edits are surgical: PyYAML `compose` gives node marks, and we splice raw
text spans so untouched regions stay byte-identical (card
ha-staging-actuation-guard: neutralize only the write paths).

What it does (all toggles/levels come from the overlay file):
  automations     -> inject `initial_state: false` into every item
  scripts/intent  -> replace `sequence:`/`action:` body with `stop: staging-noop`
  scenes          -> `entities:` emptied to {}
  shell_command   -> each command becomes a logging echo no-op
  rest_command    -> every `url:` rewritten to the configured sink
  notify          -> outbound platforms (smtp/rest/html5/...) dropped
  actuating yaml domains (switch/light/cover/...) -> platform entries dropped
                     unless platform is template/group
  mqtt/modbus/knx -> actuating entity subkeys removed, readers kept
  command_line    -> actuating subkeys dropped; sensor/binary_sensor flagged
  top-level       -> influxdb/statestream/homekit/cloud/... blocks removed
  http            -> server_host dropped (staging uses podman-net, not host
                     loopback), use_x_forwarded_for + podman trusted_proxies
                     ensured
  recorder        -> external db_url removed (falls back to local sqlite)
  .storage        -> core.config_entries: write-capable domains disabled_by=user
                     core.entity_registry: automation.* disabled_by=user

`verify` exits non-zero when a residual write path is found, and prints WARN
lines for review-tier findings (kept command_line sensors, cloned secrets,
enabled review-domain config entries). `apply` writes a machine-readable
report to <config>/.staging-guard/report.json.
"""

import argparse
import copy
import json
import os
import sys
import time

import yaml


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OVERLAY = os.path.join(
    REPO, "docs", "ssot", "infrastructure", "ssot.home-assistant.staging-overlay.yml"
)

AUTOMATION_KEYS = ("automation",)
SCRIPT_KEYS = ("script",)
INTENT_KEYS = ("intent_script",)
SCENE_KEYS = ("scene",)
AUTOMATION_ITEM_HINTS = {"trigger", "triggers", "action", "actions", "use_blueprint"}
SCRIPT_ENTRY_HINTS = {"sequence", "alias", "fields", "mode", "icon", "description"}
SCRIPT_STUB_STOP = "staging-noop"

# non-entity keys under mqtt/modbus/knx blocks — connection tuning, kept quietly
NONENTITY_SUBKEYS = {
    "broker", "port", "host", "username", "password", "discovery",
    "discovery_prefix", "client_id", "keepalive", "protocol", "certificate",
    "tls_insecure", "ca_certificates", "birth_message", "will_message",
    "name", "type", "delay", "timeout", "close_comm_on_error",
    "retry_on_empty", "message_wait_milliseconds", "tunneling", "routing",
    "individual_address", "connection_type", "local_ip", "multicast_group",
    "multicast_port", "rate_limit", "state_updater", "expose", "event",
}


def log(msg):
    print(f"[staging-overlay] {msg}")


# ---------------------------------------------------------------------------
# overlay loading / merging
# ---------------------------------------------------------------------------

def _merge(base, extra):
    """instance override merge: lists append, dicts deep-merge, scalars replace."""
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif isinstance(v, list) and isinstance(out.get(k), list):
            out[k] = out[k] + v
        else:
            out[k] = v
    return out


def load_overlay(path, instance=None):
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    overlay = doc.get("overlay", {})
    inst = (doc.get("instances") or {}).get(instance)
    if inst:
        overlay = _merge(overlay, inst)
    return overlay


# ---------------------------------------------------------------------------
# text-splice primitives
# ---------------------------------------------------------------------------

class FileEdits:
    """Accumulate char-span edits; apply bottom-up with overlap discard."""

    def __init__(self, text):
        self.text = text
        self.line_starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self.line_starts.append(i + 1)
        self.edits = []        # (start, end, new_text, note)
        self.dropped = []      # edits discarded because inside a removed span

    def line_start(self, line):
        if line >= len(self.line_starts):
            return len(self.text)
        return self.line_starts[line]

    def add(self, start, end, new_text, note):
        self.edits.append((start, end, new_text, note))

    def result(self):
        # Drop edits contained inside a kept wider edit — except zero-length
        # inserts sitting on a span boundary (e.g. two insertions at the same
        # anchor point must both land).
        spans = []
        for i, e in sorted(enumerate(self.edits),
                           key=lambda t: (t[1][0], -(t[1][1]), -t[0])):
            contained = False
            for s in spans:
                if s[0] <= e[0] and e[1] <= s[1] and not (
                        e[0] == e[1] and e[0] in (s[0], s[1])):
                    contained = True
                    break
            if contained:
                self.dropped.append(e)
            else:
                spans.append(e)
        out = self.text
        for start, end, new_text, _ in sorted(
                spans, key=lambda x: x[0], reverse=True):
            out = out[:start] + new_text + out[end:]
        return out


def scalar_text(node):
    return getattr(node, "value", "")


def node_end_line_excl(fe, node):
    """Line index just past the node's last content line.

    PyYAML marks: end_mark.column == 0 means the node ended before that
    line's content. For block collections end_mark points at the *next
    sibling token* (e.g. the next `- ` marker) — column > 0 but only
    whitespace/`-` precedes it on the line, so that line is not ours.
    Column > 0 with real content before the mark means the node ends
    mid-line and the whole line is ours.
    """
    line = node.end_mark.line
    if node.end_mark.column > 0:
        prefix = fe.text[fe.line_start(line):node.end_mark.index]
        if prefix.strip() not in ("", "-"):
            line += 1
    return line


def node_span_end_index(fe, node):
    """Char index just past the node's last line (inclusive newline)."""
    return fe.line_start(node_end_line_excl(fe, node))


def pair_span(fe, knode, vnode):
    """Char span covering a `key: value` pair's whole lines.
    Returns None when the key does not sit at the line's first non-space
    position (e.g. `- key:` inline item) — caller should flag instead."""
    ls = fe.line_start(knode.start_mark.line)
    prefix = fe.text[ls:knode.start_mark.index]
    if prefix.strip():
        return None
    return ls, node_span_end_index(fe, vnode)


def item_span(fe, item_node):
    """Char span covering a whole block sequence item incl. its `- ` line."""
    ls = fe.line_start(item_node.start_mark.line)
    return ls, node_span_end_index(fe, item_node)


def block_insert_index(fe, map_node):
    """Char index where a new line may be inserted just after map_node ends."""
    return fe.line_start(node_end_line_excl(fe, map_node))


def mapping_pairs(node):
    return node.value if isinstance(node, yaml.MappingNode) else []


def find_key(map_node, name):
    for k, v in mapping_pairs(map_node):
        if scalar_text(k) == name:
            return k, v
    return None, None


def key_indent(map_node, fallback=0):
    pairs = mapping_pairs(map_node)
    if pairs:
        return pairs[0][0].start_mark.column
    return fallback


def is_domain_key(kname, bases):
    """`script` or `script foo` merge-style keys."""
    for b in bases:
        if kname == b or kname.startswith(b + " "):
            return True
    return False


def truthy(v):
    return str(v).strip().lower() in ("true", "on", "yes", "1")


def _nl_prefix(text, pos):
    """Prepend a newline when the insertion point glues onto a non-empty
    line (e.g. EOF without trailing newline)."""
    if pos > 0 and pos <= len(text) and text[pos - 1] not in ("\n",):
        return "\n"
    return ""


# ---------------------------------------------------------------------------
# the transform / audit engine
# ---------------------------------------------------------------------------

class Engine:
    def __init__(self, overlay, mode, report, dry=False):
        self.ov = overlay
        self.mode = mode              # "apply" or "verify"
        self.dry = dry                # apply-scan but never write
        self.rep = report             # dict with changes/warnings/failures

    # -- findings ------------------------------------------------------------

    def change(self, path, rule, detail):
        self.rep["changes"].append({"file": path, "rule": rule, "detail": detail})

    def warn(self, path, rule, detail):
        self.rep["warnings"].append({"file": path, "rule": rule, "detail": detail})

    def fail(self, path, rule, detail):
        self.rep["failures"].append({"file": path, "rule": rule, "detail": detail})

    def _act(self, path, rule, detail, fe, span, new_text):
        """In apply mode register the edit; in verify mode record a failure
        (the offending content is still present)."""
        if self.mode == "apply":
            fe.add(span[0], span[1], new_text, f"{rule}: {detail}")
            self.change(path, rule, detail)
        else:
            self.fail(path, rule, detail)

    # -- yaml entry point ------------------------------------------------------

    def process_yaml(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            self.warn(path, "read", f"skipped unreadable file: {e}")
            return
        try:
            root = yaml.compose(text, Loader=yaml.SafeLoader)
        except yaml.YAMLError as e:
            self.warn(path, "parse", f"skipped unparseable yaml: {e}")
            return
        if root is None:
            return
        fe = FileEdits(text)
        base = os.path.basename(path).lower()

        # root-level sequence: automations.yaml / scenes.yaml style
        if isinstance(root, yaml.SequenceNode):
            for item in root.value:
                if not isinstance(item, yaml.MappingNode):
                    continue
                keys = {scalar_text(k) for k, _ in mapping_pairs(item)}
                if keys & AUTOMATION_ITEM_HINTS or (
                        base.startswith("automation") and "alias" in keys | {"id"}):
                    self._neutralize_automation(fe, path, item)
                elif "entities" in keys and not keys & {"platform", "trigger", "triggers", "action", "actions"}:
                    self._neutralize_scene(fe, path, item)
        # root-level mapping: scripts.yaml style — any root pair whose value is a
        # mapping with a `sequence:`/`action:` body is a script entry and gets
        # stubbed. Known HA domain keys never carry `sequence:` children at root,
        # so this can't hit real config domains.
        elif isinstance(root, yaml.MappingNode):
            for knode, vnode in mapping_pairs(root):
                if not isinstance(vnode, yaml.MappingNode):
                    continue
                if find_key(vnode, "sequence")[1] is not None or \
                        find_key(vnode, "action")[1] is not None:
                    self._neutralize_script(fe, path, vnode, scalar_text(knode))
        self._walk(fe, path, root, at_root=True)

        if self.mode == "apply" and not self.dry and fe.edits:
            out = fe.result()
            if out != text:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(out)
        for e in fe.dropped:
            self.warn(path, "edit-suppressed", f"edit inside a removed span skipped: {e[3]}")

    # -- recursive walk --------------------------------------------------------

    def _walk(self, fe, path, node, at_root=False, container_key=""):
        if isinstance(node, yaml.MappingNode):
            for knode, vnode in list(node.value):
                handled = self._handle_pair(fe, path, knode, vnode,
                                            at_root, container_key)
                if not handled:
                    self._walk(fe, path, vnode, at_root=False,
                               container_key=scalar_text(knode))
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                self._walk(fe, path, item, at_root=False,
                           container_key=container_key)

    def _handle_pair(self, fe, path, knode, vnode, at_root, container_key=""):
        k = scalar_text(knode)
        ov = self.ov

        # --- automations --------------------------------------------------
        if is_domain_key(k, AUTOMATION_KEYS) and isinstance(vnode, yaml.SequenceNode):
            for item in vnode.value:
                if isinstance(item, yaml.MappingNode):
                    self._neutralize_automation(fe, path, item)
            return True

        # --- scripts / intent scripts --------------------------------------
        if (is_domain_key(k, SCRIPT_KEYS) or is_domain_key(k, INTENT_KEYS)) \
                and isinstance(vnode, yaml.MappingNode):
            for name_node, cfg in mapping_pairs(vnode):
                if isinstance(cfg, yaml.MappingNode):
                    self._neutralize_script(fe, path, cfg, scalar_text(name_node))
            return True

        # --- scenes --------------------------------------------------------
        if is_domain_key(k, SCENE_KEYS) and isinstance(vnode, yaml.SequenceNode):
            for item in vnode.value:
                if isinstance(item, yaml.MappingNode):
                    self._neutralize_scene(fe, path, item)
            return True

        # --- shell_command ---------------------------------------------------
        if k == "shell_command" and isinstance(vnode, yaml.MappingNode):
            tmpl = ov["shell_command"]["noop_template"]
            for name_node, cmd in mapping_pairs(vnode):
                name = scalar_text(name_node)
                if not isinstance(cmd, yaml.ScalarNode):
                    self.warn(path, "shell_command", f"{name}: non-scalar command, skipped")
                    continue
                new = tmpl.replace("{name}", name)
                if self.mode == "verify":
                    if "staging-noop" not in scalar_text(cmd):
                        self.fail(path, "shell_command", f"{name}: live command still present")
                    continue
                if "staging-noop" in scalar_text(cmd):
                    continue
                fe.add(cmd.start_mark.index, cmd.end_mark.index, json.dumps(new),
                       f"shell_command {name} -> noop")
                self.change(path, "shell_command",
                            f"{name}: {scalar_text(cmd)[:80]!r} -> noop")
            return True

        # --- rest_command ----------------------------------------------------
        if k == "rest_command" and isinstance(vnode, yaml.MappingNode):
            sink = ov["rest_command"]["sink_url"]
            for name_node, cfg in mapping_pairs(vnode):
                name = scalar_text(name_node)
                if not isinstance(cfg, yaml.MappingNode):
                    self.warn(path, "rest_command", f"{name}: unexpected shape, skipped")
                    continue
                uk, uv = find_key(cfg, "url")
                if uv is None or not isinstance(uv, yaml.ScalarNode):
                    self.warn(path, "rest_command", f"{name}: no url key, skipped")
                    continue
                if scalar_text(uv) == sink:
                    continue
                if self.mode == "verify":
                    self.fail(path, "rest_command",
                              f"{name}: url {scalar_text(uv)[:80]!r} != sink")
                    continue
                fe.add(uv.start_mark.index, uv.end_mark.index, json.dumps(sink),
                       f"rest_command {name} url -> sink")
                self.change(path, "rest_command",
                            f"{name}: {scalar_text(uv)[:80]!r} -> {sink}")
            return True

        # --- notify ----------------------------------------------------------
        if k == "notify" and isinstance(vnode, yaml.SequenceNode):
            drop = set(ov["notify"]["drop_platforms"])
            for item in vnode.value:
                if not isinstance(item, yaml.MappingNode):
                    continue
                pk, pv = find_key(item, "platform")
                platform = scalar_text(pv)
                if platform not in drop:
                    continue
                span = item_span(fe, item)
                self._act(path, "notify",
                          f"dropped outbound platform {platform!r}", fe, span, "")
            return True

        # --- command_line modern list -----------------------------------------
        if k == "command_line" and isinstance(vnode, yaml.SequenceNode):
            drop_d = set(ov["command_line"]["drop_domains"])
            keep_d = set(ov["command_line"]["keep_domains"])
            for item in vnode.value:
                if not isinstance(item, yaml.MappingNode):
                    continue
                pairs = mapping_pairs(item)
                for dk, dv in pairs:
                    d = scalar_text(dk)
                    if d in drop_d:
                        if len(pairs) == 1:
                            span = item_span(fe, item)
                        else:
                            span = pair_span(fe, dk, dv)
                        if span is None:
                            self.warn(path, "command_line",
                                      f"actuating subkey {d!r} in mixed item — manual review")
                        else:
                            self._act(path, "command_line",
                                      f"dropped actuating domain {d!r}", fe, span, "")
                    elif d in keep_d:
                        nk, nv = find_key(dv, "name")
                        self.warn(path, "command_line",
                                  f"kept command_line {d} {scalar_text(nv)!r} — "
                                  "polled shell command, review for side effects")
            return True

        # --- mqtt/modbus/knx entity subkeys ------------------------------------
        if k in ov["strip_entity_subkeys"]["domains"]:
            drop_s = set(ov["strip_entity_subkeys"]["drop_subkeys"])
            keep_s = set(ov["strip_entity_subkeys"]["keep_subkeys"])
            containers = []
            if isinstance(vnode, yaml.MappingNode):
                containers = [vnode]
            elif isinstance(vnode, yaml.SequenceNode):
                containers = [i for i in vnode.value if isinstance(i, yaml.MappingNode)]
            for cont in containers:
                for sk, sv in mapping_pairs(cont):
                    s = scalar_text(sk)
                    if s in drop_s:
                        span = pair_span(fe, sk, sv)
                        if span is None:
                            self.warn(path, f"{k}-subkeys",
                                      f"actuating subkey {s!r} inline — manual review")
                        else:
                            self._act(path, f"{k}-subkeys",
                                      f"dropped actuating subkey {s!r}", fe, span, "")
                    elif s in keep_s or s in NONENTITY_SUBKEYS:
                        continue
                    else:
                        self.warn(path, f"{k}-subkeys", f"unknown subkey {s!r} kept — review")
            return True

        # --- actuating yaml platform domains ------------------------------------
        if k in ov["actuating_domains"]["domains"]:
            keep_p = set(ov["actuating_domains"]["keep_platforms"])
            if isinstance(vnode, yaml.SequenceNode):
                for item in vnode.value:
                    if not isinstance(item, yaml.MappingNode):
                        continue
                    pk, pv = find_key(item, "platform")
                    platform = scalar_text(pv)
                    if pv is None:
                        # modern single-entity mapping (e.g. under template:)
                        self.warn(path, "actuating-domain",
                                  f"{k}: item without platform kept — review")
                        continue
                    if platform in keep_p:
                        continue
                    span = item_span(fe, item)
                    self._act(path, "actuating-domain",
                              f"{k}: dropped platform {platform!r} entry", fe, span, "")
            elif isinstance(vnode, yaml.MappingNode):
                # single-entity mapping form — template:/command_line:/etc.
                # parents are already handled (or only call neutralized
                # services), so it is quiet-keep; elsewhere flag for review.
                if container_key not in ("template", "command_line", "rest"):
                    self.warn(path, "actuating-domain",
                              f"{k}: mapping form kept — review")
            return True

        # --- root-only rules ----------------------------------------------------
        if not at_root:
            return False

        if k in ov["drop_top_level_keys"]:
            span = pair_span(fe, knode, vnode)
            if span is None:
                self.warn(path, "drop-block", f"{k}: not at line start — manual review")
            else:
                self._act(path, "drop-block", f"removed top-level block {k!r}", fe, span, "")
            return True
        if k in ov["flag_top_level_keys"]:
            self.warn(path, "flag-block", f"top-level {k!r} kept — review")
            return True
        if k == "http" and isinstance(vnode, yaml.MappingNode):
            self._handle_http(fe, path, vnode)
            return True
        if k == "recorder" and isinstance(vnode, yaml.MappingNode):
            self._handle_recorder(fe, path, vnode)
            return True
        if k == "homeassistant" and isinstance(vnode, yaml.MappingNode):
            self._handle_homeassistant(fe, path, vnode)
            return True

    # -- per-rule handlers -----------------------------------------------------

    def _neutralize_automation(self, fe, path, item):
        if not self.ov["automation"]["inject_initial_state_off"]:
            return
        _, iv = find_key(item, "initial_state")
        alias = ""
        _, av = find_key(item, "alias")
        if av is not None:
            alias = scalar_text(av)
        tag = f"automation {alias or scalar_text(find_key(item, 'id')[1] or '') or '<unnamed>'}"
        if iv is not None:
            if not truthy(scalar_text(iv)):
                return  # already off
            if self.mode == "verify":
                self.fail(path, "automation", f"{tag}: initial_state still true")
                return
            fe.add(iv.start_mark.index, iv.end_mark.index, "false",
                   f"{tag}: initial_state -> false")
            self.change(path, "automation", f"{tag}: initial_state true -> false")
            return
        # insert a new `initial_state: false` line after the item's last line
        if self.mode == "verify":
            self.fail(path, "automation", f"{tag}: missing initial_state: false")
            return
        indent = key_indent(item)
        pos = block_insert_index(fe, item)
        fe.add(pos, pos, _nl_prefix(fe.text, pos)
               + " " * indent + "initial_state: false\n",
               f"{tag}: +initial_state: false")
        self.change(path, "automation", f"{tag}: +initial_state: false")

    def _stub_lines(self, indent):
        stub = self.ov["script"]["stub_sequence"]
        txt = yaml.safe_dump(stub, default_flow_style=False, sort_keys=False)
        return "".join(" " * indent + line for line in txt.splitlines(keepends=True))

    def _neutralize_script(self, fe, path, cfg, name):
        # script bodies live under `sequence:`; intent_script entries use `action:`.
        body_key = None
        bk, bv = find_key(cfg, "sequence")
        if bk is not None:
            body_key = "sequence"
        else:
            bk, bv = find_key(cfg, "action")
            if bk is not None:
                body_key = "action"
        if bk is None:
            # no body — append a stub so the entity still loads as a no-op
            if self.mode == "verify":
                self.fail(path, "script", f"{name}: no sequence/action stubbed")
                return
            indent = key_indent(cfg, fallback=k_indent_default(cfg))
            pos = block_insert_index(fe, cfg)
            fe.add(pos, pos, _nl_prefix(fe.text, pos)
                   + " " * indent + "sequence:\n" + self._stub_lines(indent + 2),
                   f"script {name}: +stub")
            self.change(path, "script", f"{name}: added stub sequence")
            return
        if self._is_stub(bv):
            return
        if self.mode == "verify":
            self.fail(path, "script", f"{name}: live {body_key} still present")
            return
        span = pair_span(fe, bk, bv)
        if span is None:
            self.warn(path, "script", f"{name}: {body_key} inline — manual review")
            return
        indent = bk.start_mark.column
        new = " " * indent + f"{body_key}:\n" + self._stub_lines(indent + 2)
        fe.add(span[0], span[1], new, f"script {name}: stubbed")
        self.change(path, "script", f"{name}: sequence replaced with staging-noop")

    def _is_stub(self, vnode):
        """True when the body is exactly the staging stub (`stop: staging-noop`)."""
        if not isinstance(vnode, yaml.SequenceNode) or len(vnode.value) != 1:
            return False
        step = vnode.value[0]
        if not isinstance(step, yaml.MappingNode) or len(step.value) != 1:
            return False
        k, _ = step.value[0]
        return scalar_text(k) == "stop"

    def _neutralize_scene(self, fe, path, item):
        if not self.ov["scene"]["empty_entities"]:
            return
        ek, ev = find_key(item, "entities")
        name = scalar_text(find_key(item, "name")[1] or find_key(item, "id")[1] or "")
        if ek is None:
            return
        if isinstance(ev, yaml.MappingNode) and not ev.value:
            return  # already {}
        if self.mode == "verify":
            self.fail(path, "scene", f"{name}: entities not emptied")
            return
        span = pair_span(fe, ek, ev)
        if span is None:
            self.warn(path, "scene", f"{name}: entities inline — manual review")
            return
        indent = ek.start_mark.column
        fe.add(span[0], span[1], " " * indent + "entities: {}\n",
               f"scene {name}: entities emptied")
        self.change(path, "scene", f"{name}: entities -> {{}}")

    def _handle_http(self, fe, path, http):
        http_ov = self.ov["http"]
        if http_ov.get("drop_server_host"):
            sk, sv = find_key(http, "server_host")
            if sv is not None:
                span = pair_span(fe, sk, sv)
                if span is None:
                    self.warn(path, "http", "server_host inline — manual review")
                else:
                    self._act(path, "http",
                              f"dropped server_host ({scalar_text(sv)})", fe, span, "")
        if http_ov.get("ensure_use_x_forwarded_for"):
            uk, uv = find_key(http, "use_x_forwarded_for")
            if uv is None:
                self._ensure_key(fe, path, http, "use_x_forwarded_for: true", "http")
            elif not truthy(scalar_text(uv)):
                if self.mode == "verify":
                    self.fail(path, "http", "use_x_forwarded_for is not true")
                else:
                    fe.add(uv.start_mark.index, uv.end_mark.index, "true",
                           "http: use_x_forwarded_for -> true")
                    self.change(path, "http", "use_x_forwarded_for -> true")
        want = [str(x) for x in http_ov.get("ensure_trusted_proxies", [])]
        if want:
            tk, tv = find_key(http, "trusted_proxies")
            if tv is None:
                lines = "trusted_proxies:\n" + "".join(
                    f"  - {p}\n" for p in want)
                self._ensure_key(fe, path, http, lines.rstrip("\n"), "http")
            elif isinstance(tv, yaml.SequenceNode):
                have = {scalar_text(i) for i in tv.value}
                missing = [p for p in want if p not in have]
                if missing:
                    if self.mode == "verify":
                        self.fail(path, "http",
                                  f"trusted_proxies missing {missing}")
                    else:
                        indent = (tv.value[0].start_mark.column
                                  if tv.value else tk.start_mark.column + 2)
                        pos = block_insert_index(fe, tv)
                        fe.add(pos, pos, _nl_prefix(fe.text, pos) +
                               "".join(" " * indent + f"- {p}\n" for p in missing),
                               f"http: trusted_proxies += {missing}")
                        self.change(path, "http", f"trusted_proxies += {missing}")
            else:
                self.warn(path, "http", "trusted_proxies non-list — manual review")

    def _ensure_key(self, fe, path, map_node, text_block, rule):
        if self.mode == "verify":
            self.fail(path, rule, f"missing key {text_block.split(':')[0]}")
            return
        indent = key_indent(map_node, fallback=map_node.start_mark.column + 2)
        pos = block_insert_index(fe, map_node)
        lines = "".join(" " * indent + line + "\n"
                        for line in text_block.split("\n"))
        fe.add(pos, pos, _nl_prefix(fe.text, pos) + lines,
               f"{rule}: inserted {text_block.split(chr(10))[0]}")
        self.change(path, rule, f"inserted {text_block.splitlines()[0]}")

    def _handle_recorder(self, fe, path, rec):
        if not self.ov["recorder"].get("drop_db_url"):
            return
        dk, dv = find_key(rec, "db_url")
        if dv is None:
            return
        span = pair_span(fe, dk, dv)
        if span is None:
            self.warn(path, "recorder", "db_url inline — manual review")
            return
        self._act(path, "recorder",
                  f"dropped external db_url ({scalar_text(dv)[:60]!r})", fe, span, "")

    def _handle_homeassistant(self, fe, path, ha):
        setkeys = self.ov.get("set_keys") or {}
        allowed = set(self.ov["homeassistant"].get("settable_keys", []))
        for key, val in setkeys.items():
            if key not in allowed:
                self.warn(path, "homeassistant", f"{key}: not in settable_keys — skipped")
                continue
            kk, kv = find_key(ha, key)
            if kv is None:
                self._ensure_key(fe, path, ha, f"{key}: {json.dumps(val)}",
                                 "homeassistant")
            elif isinstance(kv, yaml.ScalarNode):
                if scalar_text(kv) == str(val):
                    continue
                if self.mode == "verify":
                    self.fail(path, "homeassistant",
                              f"{key}: {scalar_text(kv)!r} != {val!r}")
                else:
                    fe.add(kv.start_mark.index, kv.end_mark.index,
                           json.dumps(str(val)),
                           f"homeassistant.{key} -> {val}")
                    self.change(path, "homeassistant", f"{key} -> {val}")

    # -- .storage ---------------------------------------------------------------

    def process_storage(self, config_dir):
        ov = self.ov["storage"]
        ce = os.path.join(config_dir, ".storage", "core.config_entries")
        if os.path.isfile(ce):
            self._process_config_entries(ce, ov)
        else:
            self.warn(ce, "storage", ".storage/core.config_entries missing")
        er = os.path.join(config_dir, ".storage", "core.entity_registry")
        if os.path.isfile(er):
            self._process_entity_registry(er, ov)
        else:
            self.warn(er, "storage", ".storage/core.entity_registry missing")

    def _process_config_entries(self, path, ov):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.warn(path, "storage", f"unreadable config_entries: {e}")
            return
        disabled = set(ov["disabled_config_entry_domains"])
        review = set(ov["review_config_entry_domains"])
        changed = False
        for ent in data.get("data", {}).get("entries", []):
            dom = ent.get("domain")
            cur = ent.get("disabled_by")
            if dom in disabled:
                if self.mode == "verify":
                    if not cur:
                        self.fail(path, "config_entries",
                                  f"{dom} entry {ent.get('entry_id','?')[:8]} still enabled")
                    continue
                if not cur:
                    ent["disabled_by"] = "user"
                    changed = True
                    self.change(path, "config_entries",
                                f"disabled {dom} ({ent.get('title') or ent.get('entry_id')})")
            elif dom in review and not cur:
                self.warn(path, "config_entries",
                          f"review-domain {dom} entry enabled: {ent.get('title')}")
        if changed and not self.dry:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")

    def _process_entity_registry(self, path, ov):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.warn(path, "storage", f"unreadable entity_registry: {e}")
            return
        targets = set(ov["registry_disable_entity_domains"])
        changed = False
        for ent in data.get("data", {}).get("entities", []):
            eid = ent.get("entity_id", "")
            dom = eid.split(".", 1)[0]
            if dom in targets:
                if self.mode == "verify":
                    if not ent.get("disabled_by"):
                        self.fail(path, "entity_registry", f"{eid} still enabled")
                    continue
                if not ent.get("disabled_by"):
                    ent["disabled_by"] = "user"
                    changed = True
                    self.change(path, "entity_registry", f"disabled {eid}")
        if changed and not self.dry:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")

    # -- walk the tree -----------------------------------------------------------

    def process_config(self, config_dir):
        skip = set(self.ov["skip_dirs"]) | {".staging-guard"}
        for dirpath, dirnames, filenames in os.walk(config_dir):
            dirnames[:] = sorted(d for d in dirnames if d not in skip)
            for fn in sorted(filenames):
                if fn.endswith((".yaml", ".yml")):
                    self.process_yaml(os.path.join(dirpath, fn))
        self.process_storage(config_dir)


def k_indent_default(node):
    return node.start_mark.column + 2


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["apply", "verify", "audit"])
    ap.add_argument("--config", required=True, help="HA config dir (clone target)")
    ap.add_argument("--overlay", default=DEFAULT_OVERLAY)
    ap.add_argument("--instance", default=None,
                    help="target instance id — merges overlay.instances.<id>")
    ap.add_argument("--set-key", action="append", default=[],
                    metavar="KEY=VALUE",
                    help="homeassistant: overrides (name, internal_url, external_url)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config_dir = os.path.abspath(os.path.expanduser(args.config))
    if not os.path.isdir(config_dir):
        log(f"config dir not found: {config_dir}")
        return 2

    overlay = load_overlay(args.overlay, args.instance)
    set_keys = {}
    for kv in args.set_key:
        if "=" not in kv:
            log(f"bad --set-key {kv!r} (want KEY=VALUE)")
            return 2
        k, v = kv.split("=", 1)
        set_keys[k.strip()] = v.strip()
    if set_keys:
        overlay["set_keys"] = set_keys

    verify = args.cmd == "verify"
    dry = args.dry_run or args.cmd == "audit"
    mode = "verify" if verify else "apply"

    rep = {"config_dir": config_dir, "instance": args.instance,
           "mode": ("verify" if verify else ("audit" if dry else "apply")),
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "changes": [], "warnings": [], "failures": []}

    eng = Engine(overlay, mode, rep, dry=dry)
    eng.process_config(config_dir)

    n_ch = len(rep["changes"]); n_w = len(rep["warnings"]); n_f = len(rep["failures"])
    for c in rep["changes"]:
        log(f"  change [{c['rule']}] {c['file']}: {c['detail']}")
    for w in rep["warnings"]:
        log(f"  WARN   [{w['rule']}] {w['file']}: {w['detail']}")
    for f_ in rep["failures"]:
        log(f"  FAIL   [{f_['rule']}] {f_['file']}: {f_['detail']}")
    log(f"summary: {n_ch} change(s), {n_w} warning(s), {n_f} failure(s)")

    if verify:
        return 1 if n_f else 0
    if args.cmd == "apply" and not dry:
        guard = os.path.join(config_dir, ".staging-guard")
        os.makedirs(guard, exist_ok=True)
        with open(os.path.join(guard, "report.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
            f.write("\n")
        with open(os.path.join(guard, "APPLIED"), "w", encoding="utf-8") as f:
            f.write(json.dumps({k: rep[k] for k in ("at", "instance", "mode")}) + "\n")
            f.write(f"overlay={args.overlay}\n")
        log(f"report written to {guard}/report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
