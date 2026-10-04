#!/usr/bin/env node
/*
 * Caddyfile format and syntax audit.
 * Requires caddy binary to be on PATH.
 */
import { spawnSync } from "child_process";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = join(__dirname, "..", "..");
const caddyfile = join(projectRoot, "stacks", "web", "Caddyfile");

function run(cmd, args) {
  const result = spawnSync(cmd, args, { stdio: "pipe", encoding: "utf8" });
  return {
    ok: result.status === 0,
    code: result.status,
    stdout: result.stdout?.trim() || "",
    stderr: result.stderr?.trim() || "",
  };
}

// Use the host caddy binary when present; on hosts where Caddy runs
// containerized (idc02 caddy-edge quadlet), fall back to the same
// caddy:2 image via podman with the Caddyfile bind-mounted.
function caddy(args) {
  const direct = run("caddy", args);
  if (direct.code !== null) return direct;
  const containerPath = "/tmp/Caddyfile";
  const mapped = args.map((a) => (a === caddyfile ? containerPath : a));
  return run("podman", [
    "run", "--rm", "-v", `${caddyfile}:${containerPath}:Z`,
    "docker.io/library/caddy:2", "caddy", ...mapped,
  ]);
}

const fmt = caddy(["fmt", "--overwrite", caddyfile]);
const adapt = caddy(["adapt", "--config", caddyfile, "--adapter", "caddyfile"]);

if (!fmt.ok) {
  console.error(`Caddy format failed:\n${fmt.stderr || fmt.stdout}`);
  process.exit(1);
}

if (!adapt.ok) {
  console.error(`Caddy adapt failed:\n${adapt.stderr || adapt.stdout}`);
  process.exit(1);
}

console.log(
  JSON.stringify({ ok: true, file: caddyfile, message: "Caddyfile format and syntax OK" })
);
