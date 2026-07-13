#!/usr/bin/env node
/**
 * deploy/npm/friday-setup.js — the npm face of the official FRIDAY installer.
 *
 * Anyone with access to the repository installs FRIDAY with one command:
 *
 *     npx github:satvik10293/friday            # interactive install + launch
 *     npx github:satvik10293/friday --yes      # no questions
 *     npx github:satvik10293/friday --detect   # machine report only
 *
 * npx fetches the package (this source tree), and this shim finds a Python
 * >= 3.10 and hands straight off to the real installer
 * (`python -m deploy.setup.installer`) with all arguments forwarded — one
 * installer, two front doors. Node is only the delivery vehicle; no logic
 * lives here beyond locating Python.
 */

"use strict";

const { spawnSync } = require("child_process");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const MIN_PYTHON = [3, 10];

function pythonVersion(cmd, args) {
  const probe = spawnSync(cmd, [...args, "-c",
    "import sys; print('%d.%d' % sys.version_info[:2])"],
    { encoding: "utf8", timeout: 10000, windowsHide: true });
  if (probe.status !== 0 || !probe.stdout) return null;
  const m = probe.stdout.trim().match(/^(\d+)\.(\d+)$/);
  if (!m) return null;
  const version = [Number(m[1]), Number(m[2])];
  return (version[0] > MIN_PYTHON[0] ||
          (version[0] === MIN_PYTHON[0] && version[1] >= MIN_PYTHON[1]))
    ? version : null;
}

function findPython() {
  const candidates = process.platform === "win32"
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [cmd, args] of candidates) {
    if (pythonVersion(cmd, args)) return [cmd, args];
  }
  return null;
}

function main() {
  const python = findPython();
  if (!python) {
    console.error(
      "\n  FRIDAY setup needs Python >= 3.10 and none was found." +
      "\n  Install it from https://python.org" +
      (process.platform === "win32"
        ? " (or: winget install Python.Python.3.12)" : "") +
      ", then re-run this command.\n");
    process.exit(1);
  }
  const [cmd, baseArgs] = python;
  const run = spawnSync(
    cmd, [...baseArgs, "-m", "deploy.setup.installer",
          ...process.argv.slice(2)],
    { cwd: ROOT, stdio: "inherit", windowsHide: false });
  process.exit(run.status === null ? 1 : run.status);
}

main();
