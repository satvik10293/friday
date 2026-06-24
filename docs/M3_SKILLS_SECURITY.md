# FRIDAY 4.0 — M3: Skills + Security Foundation

**Status:** ✅ Delivered (code + tests + docs). Additive, strangler-fig — no 3.0 file modified; FRIDAY still boots.
**Owners:** `core/skills/` (capability layer) + `core/security/` (enforcement layer).
**Tests:** `tests/test_skills.py`, `test_permissions.py`, `test_executor.py`, `test_approvals.py`, `test_audit.py` — part of the **91/91 passing** suite.

---

## 1. What this milestone establishes

FRIDAY now has **one approved execution path for everything it does**. Every capability — present and future (vision, OCR, web search, automation, planning, local LLMs, autonomous agents) — is a **Skill**, resolved from a registry and run through a single **Executor** that enforces validation → policy → role → approval → sandbox → audit → decision log. Nothing executes silently; nothing bypasses this class.

```
caller → SkillExecutor.execute(name, args, context)
           ├─ registry.get(name)            (SkillNotFound)
           ├─ skill.validate(args)          (ValidationError)
           ├─ policy.evaluate()             (DENY → PolicyViolation; REQUIRE_APPROVAL)
           ├─ role.allows(permission)       (PermissionDenied)
           ├─ approval.request_and_wait()   (ApprovalRejected / ApprovalTimeout)
           ├─ sandbox.run(skill.run)        (SandboxTimeout) — HIGH/CRITICAL risk only
           └─ record → Audit + DecisionLog + SecurityLog + metrics + events
                     → SuccessResult | FailureResult
```

---

## 2. Architecture delivered

### `core/skills/` — capability layer
| File | Role |
|---|---|
| `skill.py` | Abstract `Skill`: `name/description/version/permission/risk_level/tags/input_schema`, `validate()`, `run()` (sync or async), `health()`, `manifest()`. |
| `permissions.py` | `Permission` (SAFE/USER_APPROVAL/ADMIN_ONLY/SYSTEM, ordered) + `RiskLevel` + `requires_approval()`. |
| `registry.py` | Thread-safe `SkillRegistry`: register/unregister/get/has/list_skills/find_by_permission; duplicate-guarded; singleton `get_registry()`. |
| `executor.py` | `SkillExecutor` — the governed pipeline (above). Sync + `aexecute`. Lazy security imports (no cycle). |
| `context.py` | `SkillContext` — trace_id, runtime, memory_service, decision_log, working_memory, user_role, caller, metadata. |
| `results.py` | `Result` / `SuccessResult` / `FailureResult` (success, data, error, error_type, metadata, duration_ms). |
| `manifests.py` | `SkillManifest` (discoverable, serializable). |
| `exceptions.py` | `SkillError` hierarchy (all recoverable → structured FailureResult). |
| `audit.py` | `AuditLog` → `data/audit.db` (every execution, survives restart). |
| `builtin/` | `memory.search` (SAFE), `memory.store` (USER_APPROVAL), `system.health` (SAFE), `system.status` (SAFE) — reference implementations + `register_builtins()`. |

### `core/security/` — enforcement layer
| File | Role |
|---|---|
| `roles.py` | `Role` (guest/user/admin/system) with `allows(permission)` clearance threshold. |
| `policies.py` | `PolicyEngine` + tag-driven default policies: `deny_shell_execution`, `deny_network_access`, `require_approval_for_messaging`, `limit_file_modification`. Effects: ALLOW / DENY / REQUIRE_APPROVAL. |
| `approvals.py` | `ApprovalManager` — request/wait (threading.Event), `approve/reject`, `list_pending`, injectable `auto_decider`, timeout. UI-ready. |
| `sandbox.py` | `Sandbox` / `ThreadSandbox` (wall-clock timeout) / `NullSandbox` — seam for future container isolation + resource caps. |
| `validation.py` | `validate_args`, `sanitize_shell`, `is_safe_path` (for future file/automation skills). |
| `security_log.py` | `SecurityLog` → `data/security.db`: failed approvals, permission/policy violations, suspicious activity. |

---

## 3. Permission + role model

| Permission | Examples | Gate |
|---|---|---|
| SAFE | read memory, search, health | runs freely |
| USER_APPROVAL | send message, write file, store memory | user role **+ approval** |
| ADMIN_ONLY | shell, manage services | admin role **+ approval** |
| SYSTEM | modify runtime, alter policies | system role **+ approval** |

| Role | Clearance |
|---|---|
| guest | SAFE |
| user | SAFE, USER_APPROVAL |
| admin | + ADMIN_ONLY |
| system | + SYSTEM |

Role clearance is a threshold over the ordered `Permission` enum; approval is a separate gate triggered by permission level **or** a REQUIRE_APPROVAL policy (so a SAFE messaging skill still needs approval).

---

## 4. Observability integration (nothing executes silently)

Every execution:
- runs under a **trace id** (from context or freshly minted);
- writes an **audit row** (`data/audit.db`): trace_id, skill, caller, role, permission, approved, duration, success, error, result_summary;
- writes a **decision row** (M1 `DecisionLog`): intent=skill, `skills_invoked`, confidence, latency_ms, outcome, `was_autonomous` (caller≠"user");
- increments **metrics** (executions / success / failure);
- emits runtime **events** (reusing the existing `Signal` taxonomy: `ACTION_EXECUTE` on start, `UI_UPDATE` on success, `MODULE_ERROR` on failure) when a runtime is present;
- on security-relevant failures, writes a **security event** (permission_violation / failed_approval / policy_violation / suspicious).

---

## 5. Integration with M1 + M2

- **Runtime (M1):** async skills run via the new `Runtime.submit_coro()` (added this milestone — propagates results/exceptions, unlike fire-and-forget `spawn`). Events flow through the live bus. Blocking callers can use `aexecute`.
- **Memory (M2):** `memory.search` / `memory.store` operate through `SkillContext.memory_service` — the first real consumers of the Memory Service, and the template for all future data-touching skills.
- **Observability (M1):** the Decision Log is the shared "why" record; the Audit Log is the "what"; the Security Log is the "what went wrong".

---

## 6. Test coverage (44 tests)

- **permissions (5):** ordering; `requires_approval`; full role×permission clearance matrix; `get_role`.
- **skills (13):** manifest; validation (missing/wrong-type/tuple-type); builtin runs (search/store/health/status); registry register/get/has/len; duplicate rejection; missing get; `register_builtins` + `find_by_permission`; idempotent registration.
- **executor (9):** SAFE success; SkillNotFound→structured failure; validation failure; **role denied + security event**; **async skill**; **trace→decision-log propagation**; metrics; **skill crash isolation**; **policy DENY (shell)**.
- **approvals (6):** executor auto-approve/auto-reject; external approve/reject via thread; timeout; **messaging policy forces approval** (approve + reject paths).
- **audit (4):** record/query/stats; persist across reopen; security-log record/filter; executor writes audit row.

**Failure/recovery classes:** unknown skill, bad input, denied role, rejected/timed-out approval, policy denial, crashing skill — all produce a structured `FailureResult` and a durable record; the executor never raises to the caller.

---

## 7. Bug caught by the tests (worth recording)

`SkillRegistry` defines `__len__`, so an **empty registry is falsy**. The executor's `self._registry = registry or get_registry()` silently dropped a passed-in empty registry for the global singleton. Fixed with explicit `is not None` checks across all injected dependencies. This is exactly the kind of truthiness trap that turns into "works in prod, not in tests" (or worse) — the suite caught it immediately.

---

## 8. Scalability + future outlook

- **Every future capability is a Skill** — vision/OCR/web/automation/planning/local-LLM/autonomous-agents all inherit validation, permissions, approvals, audit, and tracing for free.
- **Policies are declarative + tag-driven** — new restrictions don't touch skill code.
- **Sandbox is a stable seam** — `ThreadSandbox` today; process/container isolation and resource caps slot in behind the same interface without changing the executor or skills.
- **Approvals are UI-ready** — `list_pending()` + `approve/reject` is exactly what Mission Control (a later milestone) will render.
- **The official pipeline is now real:** Runtime → Brain → Memory → Skills → Security → Audit.

---

## 9. Known follow-ups (tracked, not gold-plated)

- Hot-loading / plugin discovery for skills (registry is ready; loader is future).
- Resource limits (CPU/mem) in the sandbox; process isolation for CRITICAL skills.
- Migrate the legacy `FridayAction` (30+ commands) into permissioned skills, then route the brain through the executor — a later rewiring step (**needs Git installed first**).
- Mission Control surfaces (`list_pending`, audit/security/decision feeds) — its own milestone.

---

*M3 delivered per the charter: every capability is a Skill; no direct action bypasses the Skill system; production-grade, typed, documented, and fully observable.*
