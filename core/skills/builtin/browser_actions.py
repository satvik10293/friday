"""
core/skills/builtin/browser_actions.py — FRIDAY driving Chrome.

Governed skills over core/web/browser.BrowserController. Reading and navigating
are SAFE (low-risk); clicking and typing on a live, logged-in page are
USER_APPROVAL (owner-confirmed, never voice-run unattended). All run through the
usual SkillExecutor pipeline (policy -> role -> approval -> audit + DecisionLog).

If Playwright/Chrome isn't set up, each skill returns
{"ok": False, "reason": "not_available"} and FRIDAY says how to enable it.
"""

from __future__ import annotations

from typing import Any

from core.skills.permissions import Permission, RiskLevel
from core.skills.skill import Skill


def _browser():
    from core.web.browser import get_browser
    return get_browser()


class BrowserOpenSkill(Skill):
    name = "browser.open"
    description = "Open a web page in FRIDAY's Chrome and report its title."
    permission = Permission.SAFE
    risk_level = RiskLevel.MEDIUM
    tags = ("web", "browser", "navigate")
    input_schema = {"url": {"required": True, "type": str}}

    def run(self, context: Any, **kwargs) -> dict:
        return _browser().open(str(kwargs.get("url", "")))


class BrowserReadSkill(Skill):
    name = "browser.read"
    description = "Read the text of the page currently open in FRIDAY's Chrome."
    permission = Permission.SAFE
    risk_level = RiskLevel.LOW
    tags = ("web", "browser", "read")

    def run(self, context: Any, **kwargs) -> dict:
        return _browser().read()


class BrowserScreenshotSkill(Skill):
    name = "browser.screenshot"
    description = "Screenshot the page currently open in FRIDAY's Chrome."
    permission = Permission.SAFE
    risk_level = RiskLevel.LOW
    tags = ("web", "browser", "read")

    def run(self, context: Any, **kwargs) -> dict:
        return _browser().screenshot(kwargs.get("path"))


class BrowserClickSkill(Skill):
    name = "browser.click"
    description = "Click an element on the current page by its visible text."
    permission = Permission.USER_APPROVAL           # interacts with a live page
    risk_level = RiskLevel.HIGH
    tags = ("web", "browser", "act")
    input_schema = {"text": {"required": True, "type": str}}

    def run(self, context: Any, **kwargs) -> dict:
        return _browser().click(str(kwargs.get("text", "")))


class BrowserTypeSkill(Skill):
    name = "browser.type"
    description = "Type text into the current page in FRIDAY's Chrome."
    permission = Permission.USER_APPROVAL
    risk_level = RiskLevel.HIGH
    tags = ("web", "browser", "act")
    input_schema = {"text": {"required": True, "type": str},
                    "selector": {"type": str}}

    def run(self, context: Any, **kwargs) -> dict:
        return _browser().type_text(str(kwargs.get("text", "")),
                                    selector=kwargs.get("selector"))


BROWSER_SKILLS = [BrowserOpenSkill, BrowserReadSkill, BrowserScreenshotSkill,
                  BrowserClickSkill, BrowserTypeSkill]


def register_browser_skills(registry) -> None:
    for cls in BROWSER_SKILLS:
        if not registry.has(cls.name):
            registry.register(cls())
