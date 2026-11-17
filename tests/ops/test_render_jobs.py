"""render-jobs coverage for the dispatcher->systemd migration (OPS-0790,
2026-10-29).

Pins the rendered-timer contract that replaced the last eight
dispatch:dispatcher registry entries: host/cadence/timeout/cwd/exec/
env_file/condition_path must survive the conversion verbatim in the
generated units, the podman stale --name preclean the dispatcher carried
(OPS-0531 wedge) must come back as a best-effort ExecStartPre, no host
may render chaba-jobs.* once the fleet has zero dispatcher jobs, and the
committed systemd/generated/ tree must equal render(manifest) — the
guard that would have caught the years of stale generated units the
migration swept out.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/render-jobs.py"

spec = importlib.util.spec_from_file_location("render_jobs", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["render_jobs"] = mod
spec.loader.exec_module(mod)

GENERATED = REPO / "systemd" / "generated"

# the eight jobs migrated off dispatch:dispatcher for OPS-0790
MIGRATED = {
    "embed-lane-news":        ("idc03",     "1h",  300,  "60min"),
    "embed-lane-lessons":     ("idc03",     "1d",  600,  "1440min"),
    "embed-lane-banks":       ("idc02",     "1d",  2700, "1440min"),
    "yomi-update-active":     ("idc03",     "15m", 120,  "15min"),
    "mcp-debug-h3-sync":      ("tony_dell", "10m", 60,   "10min"),
    "tony-dell-health-snapshot": ("tony_dell", "5m", 60, "5min"),
    "network-scan-tony":      ("tony_dell", "15m", 120,  "15min"),
    "lesson-drift-check":     ("tony_dell", "1d",  90,   "1440min"),
}


def manifest():
    return mod.load_manifest()


def job(man, jid):
    return next(j for j in man["jobs"] if j["id"] == jid)


def base_job(jid="j", **kw):
    j = {"id": jid, "name": jid, "host": "idc03",
         "dispatch": "systemd", "every": "5m", "exec": "/bin/true"}
    j.update(kw)
    return j


class Manifest(unittest.TestCase):
    def test_manifest_validates_clean(self):
        self.assertEqual(mod.validate(manifest()), [])

    def test_no_dispatcher_jobs_remain(self):
        left = [j["id"] for j in manifest()["jobs"]
                if j["dispatch"] == "dispatcher"]
        self.assertEqual(left, [])

    def test_migrated_jobs_all_present_on_expected_hosts(self):
        man = manifest()
        for jid, (host, _every, _t, _cal) in MIGRATED.items():
            j = job(man, jid)
            self.assertEqual(j["dispatch"], "systemd", jid)
            self.assertEqual(j["host"], host, jid)


class RenderedUnits(unittest.TestCase):
    """Every dispatcher field must land in the rendered unit verbatim."""

    @classmethod
    def setUpClass(cls):
        cls.man = manifest()
        cls.units = {}
        for host in cls.man["config"]["repo"]:
            cls.units[host] = mod.render_host(cls.man, host)

    def units_for(self, jid):
        host = MIGRATED[jid][0]
        return self.units[host][f"{jid}.service"], \
            self.units[host][f"{jid}.timer"]

    def test_each_migrated_job_has_service_and_timer(self):
        for jid in MIGRATED:
            svc, tim = self.units_for(jid)
            self.assertIn("[Service]", svc, jid)
            self.assertIn("[Timer]", tim, jid)
            self.assertIn("WantedBy=timers.target", tim, jid)
            self.assertIn("Type=oneshot", svc, jid)

    def test_cadence_and_timeout_preserved(self):
        for jid, (_host, _every, timeout_s, active) in MIGRATED.items():
            svc, tim = self.units_for(jid)
            self.assertIn("OnBootSec=1min", tim, jid)
            self.assertIn(f"OnUnitActiveSec={active}", tim, jid)
            self.assertIn(f"TimeoutStartSec={timeout_s}", svc, jid)

    def test_exec_cwd_env_file_condition_path_preserved(self):
        man = manifest()
        for jid in MIGRATED:
            j = job(man, jid)
            svc, _ = self.units_for(jid)
            for e in mod.job_execs(j):
                self.assertIn(f"ExecStart={mod.esc(e)}", svc, jid)
            if j.get("cwd"):
                self.assertIn(f"WorkingDirectory={j['cwd']}", svc, jid)
            if j.get("env_file"):
                self.assertIn(f"EnvironmentFile={j['env_file']}", svc, jid)
            for p in ([j["condition_path"]] if isinstance(
                    j.get("condition_path"), str) else
                    j.get("condition_path") or []):
                self.assertIn(f"ConditionPathExists={p}", svc, jid)

    def test_podman_preclean_rendered_for_migrated_job(self):
        svc, _ = self.units_for("yomi-update-active")
        self.assertIn(
            "ExecStartPre=-/usr/bin/podman rm -f yomi-update-active", svc)
        self.assertLess(svc.index("ExecStartPre"), svc.index("ExecStart="))

    def test_no_chaba_jobs_units_rendered_anywhere(self):
        for host, units in self.units.items():
            self.assertNotIn("chaba-jobs.service", units, host)
            self.assertNotIn("chaba-jobs.timer", units, host)


class PodmanPreclean(unittest.TestCase):
    """The dispatcher's stale-name guard as a renderer feature."""

    def svc(self, **kw):
        return mod.render_service(base_job(**kw), manifest())

    def test_preclean_for_space_and_equals_name_forms(self):
        svc = self.svc(exec="/usr/bin/podman run --rm --name foo img")
        self.assertIn("ExecStartPre=-/usr/bin/podman rm -f foo", svc)
        svc = self.svc(exec="/usr/bin/podman run --rm --name=bar img")
        self.assertIn("ExecStartPre=-/usr/bin/podman rm -f bar", svc)

    def test_no_preclean_without_name_flag(self):
        svc = self.svc(exec="/usr/bin/podman run --rm img")
        self.assertNotIn("ExecStartPre", svc)

    def test_no_preclean_on_non_podman_exec_with_name_arg(self):
        svc = self.svc(exec="/usr/bin/python3 x.py --name foo")
        self.assertNotIn("ExecStartPre", svc)

    def test_preclean_failure_is_nonfatal(self):
        # '-' prefix — a missing container must not block the run
        svc = self.svc(exec="/usr/bin/podman run --name q img")
        self.assertIn("ExecStartPre=-/usr/bin/podman rm -f q", svc)

    def test_sibling_yomi_update_all_also_protected(self):
        svc = mod.render_service(job(manifest(), "yomi-update-all"),
                                 manifest())
        self.assertIn(
            "ExecStartPre=-/usr/bin/podman rm -f yomi-update-all", svc)


class ContractGuards(unittest.TestCase):
    def test_critical_true_still_rejected_on_systemd_jobs(self):
        man = {"config": {"repo": {"idc03": "%h/x"}},
               "jobs": [base_job(critical=True)]}
        self.assertTrue(any("critical" in e for e in mod.validate(man)))

    def test_dispatcher_contract_still_renders_tick_units(self):
        man = {"config": {"repo": {"h1": "%h/x"},
                          "dispatcher_tick": "1min"},
               "jobs": [{"id": "d", "name": "d", "host": "h1",
                         "dispatch": "dispatcher", "every": "5m",
                         "exec": "/bin/true"}]}
        units = mod.render_host(man, "h1")
        self.assertIn("chaba-jobs.service", units)
        self.assertIn("chaba-jobs.timer", units)
        self.assertIn("job-dispatcher.py --host h1",
                      units["chaba-jobs.service"])


class SelectiveInstall(unittest.TestCase):
    """--ids must scope render/install to only the requested job pairs so a
    host-by-host rollout cannot enable unrelated timers (OPS-0993)."""

    def test_ids_select_only_the_requested_jobs_units(self):
        man = manifest()
        units = mod.render_host(man, "tony_dell", ids={"mcp-debug-h3-sync"})
        self.assertEqual(
            sorted(units),
            ["mcp-debug-h3-sync.service", "mcp-debug-h3-sync.timer"])

    def test_ids_never_emit_other_timers_for_enable(self):
        # install enables every *.timer in the rendered set — an unrelated
        # timer name in `units` would get armed by systemctl enable --now.
        man = manifest()
        units = mod.render_host(
            man, "tony_dell",
            ids={"mcp-debug-h3-sync", "network-scan-tony"})
        timers = {n for n in units if n.endswith(".timer")}
        self.assertEqual(
            timers, {"mcp-debug-h3-sync.timer", "network-scan-tony.timer"})
        self.assertNotIn("tony-dell-health-snapshot.timer", units)
        self.assertNotIn("lesson-drift-check.timer", units)

    def test_ids_exclude_dispatcher_meta_units(self):
        # chaba-jobs.* is not a per-job pair; a selective install must not
        # rewrite or re-enable the dispatcher tick mid-rollout.
        man = {"config": {"repo": {"h1": "%h/x"},
                          "dispatcher_tick": "1min"},
               "jobs": [{"id": "d", "name": "d", "host": "h1",
                         "dispatch": "dispatcher", "every": "5m",
                         "exec": "/bin/true"},
                        {"id": "s", "name": "s", "host": "h1",
                         "dispatch": "systemd", "every": "5m",
                         "exec": "/bin/true"}]}
        units = mod.render_host(man, "h1", ids={"s"})
        self.assertEqual(sorted(units), ["s.service", "s.timer"])
        # and the unfiltered render still carries the tick units
        full = mod.render_host(man, "h1")
        self.assertIn("chaba-jobs.timer", full)

    def test_ids_none_preserves_full_host_render(self):
        man = manifest()
        self.assertEqual(
            mod.render_host(man, "tony_dell"),
            mod.render_host(man, "tony_dell", ids=None))

    def test_ids_on_wrong_host_render_nothing(self):
        man = manifest()
        # mcp-debug-h3-sync lives on tony_dell, not idc03
        self.assertEqual(
            mod.render_host(man, "idc03", ids={"mcp-debug-h3-sync"}), {})

    def test_timer_units_keeps_timer_suffix(self):
        # `systemctl enable --now <bare>` resolves to .service — the install
        # path must pass full .timer names or it arms nothing.
        units = {"a.service": "", "a.timer": "", "b.service": "",
                 "b.timer": "", "notes.txt": ""}
        self.assertEqual(mod.timer_units(units), ["a.timer", "b.timer"])


class InstallPath(unittest.TestCase):
    """main() --install end-to-end: the rollout guarantee lives at the
    systemctl boundary. A scoped install must write/reload/enable only the
    selected job's pair — unrelated timers must never appear in any
    systemctl argv (OPS-0993; render-layer scoping alone would not catch a
    regression in main()'s enable list)."""

    ENABLE = ["systemctl", "--user", "enable", "--now"]
    RELOAD = ["systemctl", "--user", "daemon-reload"]

    def _manifest(self, root):
        p = root / "jobs.yml"
        p.write_text(yaml.safe_dump({
            "config": {"repo": {"h1": "%h/x", "h2": "%h/x"},
                       "generated_dir": "gen",
                       "dispatcher_tick": "1min"},
            "jobs": [
                base_job("sel", host="h1"),
                base_job("other", host="h1"),
                # a dispatcher job on h1 renders chaba-jobs.* in the
                # unfiltered path — the unit a scoped install must spare.
                {"id": "dsp", "name": "dsp", "host": "h1",
                 "dispatch": "dispatcher", "every": "5m",
                 "exec": "/bin/true"},
                base_job("remote", host="h2"),
            ],
        }))
        return p

    def _install(self, root, *argv):
        """Run main() with a synthetic manifest + fake $HOME; returns
        (rc, systemctl argv lists, written unit names)."""
        home = root / "home"
        with mock.patch.object(mod.subprocess, "run") as run, \
                mock.patch.object(Path, "home", return_value=home), \
                mock.patch.object(sys, "argv", ["render-jobs.py", *argv]), \
                contextlib.redirect_stdout(io.StringIO()):
            run.return_value.returncode = 0
            rc = mod.main()
        cmds = [c.args[0] for c in run.call_args_list]
        dest = home / ".config/systemd/user"
        written = sorted(p.name for p in dest.iterdir()) \
            if dest.is_dir() else []
        return rc, cmds, written

    def test_ids_install_enables_only_the_selected_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            man = self._manifest(root)
            rc, cmds, written = self._install(
                root, "--manifest", str(man), "--host", "h1",
                "--ids", "sel", "--install")
        self.assertEqual(rc, 0)
        self.assertEqual(cmds.count(self.RELOAD), 1)
        enables = [c for c in cmds if c[:4] == self.ENABLE]
        self.assertEqual(enables, [self.ENABLE + ["sel.timer"]])
        for unit in ("other.service", "other.timer",
                     "remote.service", "remote.timer"):
            self.assertFalse(any(unit in c for c in cmds), unit)
        self.assertEqual(written, ["sel.service", "sel.timer"])

    def test_ids_install_never_touches_dispatcher_tick(self):
        # The rollout keeps chaba-jobs.timer live until every migrated
        # timer verifies — a selective install must neither rewrite nor
        # re-arm it even though h1 still has a dispatcher job.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            man = self._manifest(root)
            rc, cmds, written = self._install(
                root, "--manifest", str(man), "--host", "h1",
                "--ids", "sel", "--install")
        self.assertEqual(rc, 0)
        self.assertFalse(
            any("chaba-jobs.timer" in c or "chaba-jobs.service" in c
                for c in cmds))
        self.assertNotIn("chaba-jobs.timer", written)
        self.assertNotIn("chaba-jobs.service", written)

    def test_full_install_without_ids_still_arms_every_timer(self):
        # No selector -> preserved whole-host behavior, dispatcher tick
        # units included.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            man = self._manifest(root)
            rc, cmds, written = self._install(
                root, "--manifest", str(man), "--host", "h1", "--install")
        self.assertEqual(rc, 0)
        enables = [c for c in cmds if c[:4] == self.ENABLE]
        self.assertEqual(enables, [self.ENABLE + [
            "chaba-jobs.timer", "other.timer", "sel.timer"]])
        self.assertEqual(written, [
            "chaba-jobs.service", "chaba-jobs.timer",
            "other.service", "other.timer",
            "sel.service", "sel.timer"])

    def test_unknown_id_aborts_before_any_write_or_systemctl(self):
        # A typo'd rollout command must fail loudly, not silently install
        # nothing or — worse — fall back to a full install.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            man = self._manifest(root)
            rc, cmds, written = self._install(
                root, "--manifest", str(man), "--host", "h1",
                "--ids", "bogus", "--install")
        self.assertEqual(rc, 2)
        self.assertEqual(cmds, [])
        self.assertEqual(written, [])

    def test_ids_matching_no_job_on_host_runs_no_systemctl(self):
        # 'remote' lives on h2 — on h1 the install must not even
        # daemon-reload.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            man = self._manifest(root)
            rc, cmds, written = self._install(
                root, "--manifest", str(man), "--host", "h1",
                "--ids", "remote", "--install")
        self.assertEqual(rc, 0)
        self.assertEqual(cmds, [])
        self.assertEqual(written, [])


class GeneratedTree(unittest.TestCase):
    """systemd/generated/<host> must equal render(manifest) exactly —
    catches host moves / manifest edits that forget to re-render."""

    def test_generated_tree_matches_manifest(self):
        man = manifest()
        drift = []
        hosts = set(man["config"]["repo"])
        for d in GENERATED.iterdir():
            if d.is_dir():
                hosts.add(d.name)
        for host in hosts:
            want = mod.render_host(man, host)
            d = GENERATED / host
            have = {f.name: f.read_text() for f in d.iterdir()} \
                if d.is_dir() else {}
            for name in sorted(set(want) | set(have)):
                if name not in want:
                    drift.append(f"{host}/{name}: stale, not in manifest")
                elif name not in have:
                    drift.append(f"{host}/{name}: missing from tree")
                elif have[name] != want[name]:
                    drift.append(f"{host}/{name}: content differs")
        self.assertEqual(drift, [])


if __name__ == "__main__":
    unittest.main()
