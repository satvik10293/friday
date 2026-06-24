"""
friday_codex_agent.py — Friday 3.0
The coding module's built-in self-improvement sub-agent.

Runs in the background while Friday is up ("24/7"), continuously CHECKING HERSELF
(static health of her own core modules) and writing down WHAT SHE WANTS TO DO as
proposals in a DEDICATED Obsidian vault — separate from her knowledge vault.

Safety model (chosen by Satvik):
  • It NEVER edits live code on its own.
  • Every idea becomes a "pending" proposal note in the proposals vault.
  • A human reviews and confirms (status -> approved).
  • Applying an approved proposal is a deliberate, backed-up step.

So the loop is:  self-check  ->  propose (pending)  ->  human confirms  ->  apply.
"""

import os
import re
import sys
import ast
import time
import shutil
import hashlib
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.codex_agent")

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── locations ───────────────────────────────────────────────────────────────--
CORE_DIR        = _HERE.parent
PROPOSALS_VAULT = Path(os.environ.get("FRIDAY_PROPOSALS_VAULT", r"C:\VAULT\friday_proposals"))
BACKUP_DIR      = _ROOT / "data" / "codex_backups"
CHECK_INTERVAL  = int(os.environ.get("FRIDAY_CODEX_INTERVAL", "1800"))   # seconds
_MAX_TODO_PROPOSALS = 5     # cap improvement proposals per cycle to avoid flooding

_VALID_STATUS = ("pending", "approved", "rejected", "applied")
_REPORT_NOTE  = "_self_check_report.md"   # the live health journal (not a proposal)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").lower())
    s = re.sub(r"[\s-]+", "-", s).strip("-")[:48]
    return s or "proposal"


# ── markdown proposal (de)serialization ─────────────────────────────────────────
_FM_FIELDS = ("id", "created", "status", "kind", "target", "title", "signature")


def _serialize(p: dict) -> str:
    lines = ["---"]
    for k in _FM_FIELDS:
        lines.append(f"{k}: {p.get(k, '')}")
    lines.append("---\n")
    lines.append("## What she wants to do\n" + (p.get("intent", "") or "") + "\n")
    lines.append("## Why\n" + (p.get("why", "") or "") + "\n")
    lines.append("## Proposed change\n" + (p.get("change", "") or "") + "\n")
    return "\n".join(lines)


def _parse_frontmatter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        if ": " in ln:
            k, v = ln.split(": ", 1)
            out[k.strip()] = v.strip()
        elif ln.rstrip().endswith(":"):
            out[ln.rstrip()[:-1].strip()] = ""
    return out


def _existing_signatures() -> set:
    sigs = set()
    if not PROPOSALS_VAULT.exists():
        return sigs
    for p in PROPOSALS_VAULT.glob("*.md"):
        if p.name == _REPORT_NOTE:
            continue
        try:
            fm = _parse_frontmatter(p.read_text(encoding="utf-8"))
            if fm.get("signature"):
                sigs.add(fm["signature"])
        except OSError:
            continue
    return sigs


def _write_proposal(issue: dict) -> Path:
    PROPOSALS_VAULT.mkdir(parents=True, exist_ok=True)
    sig = hashlib.sha256(f"{issue['target']}|{issue['title']}".encode()).hexdigest()[:12]
    pid = sig[:8]
    p = {
        "id":        pid,
        "created":   _utcnow_iso(),
        "status":    "pending",
        "kind":      issue.get("kind", "improvement"),
        "target":    issue.get("target", ""),
        "title":     issue.get("title", ""),
        "signature": sig,
        "intent":    issue.get("intent", ""),
        "why":       issue.get("why", ""),
        "change":    issue.get("change", ""),
    }
    path = PROPOSALS_VAULT / f"{_slug(issue['title'])}-{pid}.md"
    path.write_text(_serialize(p), encoding="utf-8")
    return path


# ── self-check (static, side-effect free) ───────────────────────────────────────
def self_check() -> dict:
    """Inspect Friday's own core modules. Returns a health report + issues."""
    issues: list[dict] = []
    checked = ok = 0
    for py in sorted(CORE_DIR.rglob("*.py")):
        if py.name.startswith("_") or py.name == "friday_codex_agent.py":
            continue
        checked += 1
        try:
            src = py.read_text(encoding="utf-8")
        except OSError:
            continue
        # 1. Syntax errors — concrete, must-fix.
        try:
            ast.parse(src)
            ok += 1
        except SyntaxError as e:
            issues.append({
                "kind":   "fix",
                "target": str(py.relative_to(CORE_DIR.parent)).replace(chr(92), "/"),
                "title":  f"Syntax error in {py.name}",
                "intent": f"Fix the syntax error in {py.name} around line {e.lineno}.",
                "why":    f"The module fails to parse ({e.msg}, line {e.lineno}); "
                          f"anything importing it breaks.",
                "change": f"Review line {e.lineno}: {(e.text or '').strip()}",
            })
            continue
        # 2. Improvement candidates — bare excepts (silent failures).
        for i, line in enumerate(src.splitlines(), 1):
            if line.strip() == "except:":
                issues.append({
                    "kind":   "improvement",
                    "target": str(py.relative_to(CORE_DIR.parent)).replace(chr(92), "/"),
                    "title":  f"Bare except in {py.name}:{i}",
                    "intent": f"Replace the bare 'except:' at {py.name}:{i} with a "
                              f"specific exception type.",
                    "why":    "Bare excepts swallow real errors (incl. KeyboardInterrupt) "
                              "and make bugs hard to find.",
                    "change": f"At {py.name}:{i}, catch a specific exception, e.g. "
                              f"`except Exception as e:` and log it.",
                })
    return {"checked": checked, "ok": ok, "issues": issues, "at": _utcnow_iso()}


def _write_report(report: dict, new_props: int) -> None:
    PROPOSALS_VAULT.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        "title: Self-check report\n"
        "type: report\n"
        f"updated: {report['at']}\n"
        "---\n\n"
        "# Friday — coding self-check\n\n"
        f"- Modules checked: **{report['checked']}**\n"
        f"- Parsing OK: **{report['ok']}**\n"
        f"- Open issues found: **{len(report['issues'])}**\n"
        f"- New proposals this cycle: **{new_props}**\n"
        f"- Last run: {report['at']} UTC\n\n"
        "Review the proposal notes in this vault, then approve the ones you want "
        "(set `status: approved`). Nothing is applied to live code automatically.\n"
    )
    (PROPOSALS_VAULT / _REPORT_NOTE).write_text(body, encoding="utf-8")


# ── one cycle ───────────────────────────────────────────────────────────────────
def run_once() -> dict:
    """Run a single self-check cycle: check, then file any NEW proposals."""
    report = self_check()
    known  = _existing_signatures()
    new    = 0
    for issue in report["issues"][: 1 + _MAX_TODO_PROPOSALS]:
        sig = hashlib.sha256(f"{issue['target']}|{issue['title']}".encode()).hexdigest()[:12]
        if sig in known:
            continue
        path = _write_proposal(issue)
        new += 1
        log.info("Proposal filed: %s -> %s", issue["title"], path.name)
    _write_report(report, new)
    log.info("Self-check: %d/%d modules parse OK, %d issues, %d new proposals",
             report["ok"], report["checked"], len(report["issues"]), new)
    return {"checked": report["checked"], "ok": report["ok"],
            "issues": len(report["issues"]), "new_proposals": new}


def propose_idea(title: str, intent: str, why: str = "", change: str = "",
                 target: str = "", kind: str = "improvement") -> Path:
    """Record something Friday WANTS to do as a 'pending' proposal for human review.
    Called by the main agent when she decides she'd like to change/improve herself.
    De-dupes on (target, title) so the same idea isn't filed twice."""
    sig = hashlib.sha256(f"{target}|{title}".encode()).hexdigest()[:12]
    if sig in _existing_signatures():
        # already proposed — return the existing note path
        for p in PROPOSALS_VAULT.glob("*.md"):
            if _parse_frontmatter(p.read_text(encoding="utf-8")).get("signature") == sig:
                return p
    path = _write_proposal({"kind": kind, "target": target, "title": title,
                            "intent": intent, "why": why, "change": change})
    log.info("Idea recorded for review: %s -> %s", title, path.name)
    return path


# ── background daemon ───────────────────────────────────────────────────────────
_stop   = threading.Event()
_thread: Optional[threading.Thread] = None


def _loop(interval: int):
    while not _stop.is_set():
        try:
            run_once()
        except Exception as e:
            log.error("Self-check cycle failed: %s", e)
        _stop.wait(timeout=interval)


def start(interval: int = CHECK_INTERVAL) -> None:
    """Start the 24/7 background self-check loop. Safe to call once."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval,),
                               name="codex-agent", daemon=True)
    _thread.start()
    log.info("Codex self-improvement agent started (interval=%ds, vault=%s)",
             interval, PROPOSALS_VAULT)


def stop() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=5)


# ── review / apply (human-gated) ────────────────────────────────────────────────
def list_proposals(status: Optional[str] = None) -> list[dict]:
    out = []
    if not PROPOSALS_VAULT.exists():
        return out
    for p in sorted(PROPOSALS_VAULT.glob("*.md")):
        if p.name == _REPORT_NOTE:
            continue
        fm = _parse_frontmatter(p.read_text(encoding="utf-8"))
        if not fm.get("id"):
            continue
        if status and fm.get("status") != status:
            continue
        fm["_file"] = p.name
        out.append(fm)
    return out


def set_status(proposal_id: str, status: str) -> bool:
    if status not in _VALID_STATUS:
        raise ValueError(f"status must be one of {_VALID_STATUS}")
    for p in PROPOSALS_VAULT.glob("*.md"):
        if p.name == _REPORT_NOTE:
            continue
        text = p.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        if fm.get("id") == proposal_id:
            new = re.sub(r"(?m)^status: .*$", f"status: {status}", text, count=1)
            p.write_text(new, encoding="utf-8")
            log.info("Proposal %s -> %s", proposal_id, status)
            return True
    return False


def backup_file(target_rel: str) -> Optional[Path]:
    """Back up a core file before any human-approved change is applied."""
    src = _ROOT / target_rel
    if not src.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = BACKUP_DIR / f"{src.name}.{stamp}.bak"
    shutil.copy2(src, dst)
    log.info("Backed up %s -> %s", target_rel, dst)
    return dst


# ── CLI ───────────────────────────────────────────────────────────────────────--
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    import argparse
    ap = argparse.ArgumentParser(description="Friday coding self-improvement sub-agent")
    ap.add_argument("--once",   action="store_true", help="run one self-check cycle")
    ap.add_argument("--list",   action="store_true", help="list proposals")
    ap.add_argument("--status", type=str, default="", help="filter --list by status")
    ap.add_argument("--approve", type=str, default="", help="approve a proposal id")
    ap.add_argument("--reject",  type=str, default="", help="reject a proposal id")
    args = ap.parse_args()

    if args.once:
        print("[once]", run_once())
    if args.approve:
        print("approved:", set_status(args.approve, "approved"))
    if args.reject:
        print("rejected:", set_status(args.reject, "rejected"))
    if args.list:
        for pr in list_proposals(args.status or None):
            print(f"  [{pr.get('status'):8}] {pr.get('id')}  {pr.get('kind'):11} "
                  f"{pr.get('target'):24} {pr.get('title')}")
    if not any([args.once, args.list, args.approve, args.reject]):
        print("[vault]", PROPOSALS_VAULT)
        print("Use --once to run a check, --list to review, --approve/--reject ID.")
