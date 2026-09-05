"""
Understanding vs ACTION (M59.1): clear commands trigger actions, not essays.

The pipeline separation pinned here:
· a clear device command that maps to a SAFE skill EXECUTES it (governed)
· an above-SAFE command gets the M47 approval refusal — one sentence
· a device command with no matching action gets an honest decline — one
  sentence, and the CLOUD IS NEVER CONSULTED for a command
· questions and speech-acts (explain/tell/summarize) keep the full
  understanding path untouched
"""

from __future__ import annotations

from types import SimpleNamespace

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.skills.permissions import Permission
from core.skills.results import Result


class _Skill:
    def __init__(self, permission=Permission.SAFE):
        self.permission = permission


class _Registry:
    def __init__(self, skills):
        self._skills = skills

    def get(self, name):
        return self._skills[name]


class _Skills:
    """SkillExecutor double: records executions."""

    def __init__(self, skills):
        self._registry = _Registry(skills)
        self.executed = []

    def execute(self, name, args=None, context=None):
        self.executed.append((name, dict(args or {})))
        return Result(success=True, data="ok")


class _CloudSpy:
    def __init__(self):
        self.called = 0

    def available(self):
        return True

    def reason(self, q, *, context=None):
        self.called += 1
        return SimpleNamespace(ok=True, answer="a long explanation …",
                               model="x", latency_ms=1.0)

    def status(self):
        return {}


class _IOS:
    def __init__(self):
        self.calls = 0

    def think(self, prompt, context=None, **kw):
        self.calls += 1
        return SimpleNamespace(task="general", strategy="ios", ok=True,
                               confidence=0.7, answer="ios answer",
                               models_used=[], structured={}, trace_id="t",
                               context_used={})


def _bridge(skills=None, cloud=None):
    return ConversationBridge(
        _IOS(), decision_log=_Log(), skills=skills, reasoner=cloud,
        speech=_SpeechOutput(synthesizer=lambda t: None))


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


# ── clear commands ACT ────────────────────────────────────────────────────────

def test_open_app_command_executes_the_skill_not_the_cloud():
    skills = _Skills({"app.open": _Skill()})
    cloud = _CloudSpy()
    bridge = _bridge(skills, cloud)
    resp = bridge.think("open notepad")
    assert skills.executed == [("app.open", {"name": "notepad"})]
    assert cloud.called == 0                       # acted, didn't explain
    assert "opening" in resp.answer.lower()


def test_open_url_routes_to_the_browser_skill():
    skills = _Skills({"web.open_url": _Skill(), "app.open": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("open youtube.com")
    assert skills.executed[0][0] == "web.open_url"
    assert skills.executed[0][1]["url"] == "https://youtube.com"


def test_clipboard_and_brightness_commands_act():
    skills = _Skills({"clipboard.get": _Skill(), "display.set_brightness": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("what's on my clipboard")
    bridge.think("set the brightness to 70")
    assert ("clipboard.get", {}) in skills.executed
    assert ("display.set_brightness", {"level": 70}) in skills.executed


# ── the first "run my PC" job: find-and-open a file (SAFE, on-device) ──────────

def test_open_file_by_extension_routes_to_find_open():
    skills = _Skills({"files.find_open": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("open notes.txt")
    assert ("files.find_open", {"query": "notes.txt"}) in skills.executed


def test_find_and_open_phrase_routes_to_find_open():
    skills = _Skills({"files.find_open": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("find and open report")
    assert ("files.find_open", {"query": "report"}) in skills.executed


def test_open_the_file_called_x_routes_to_find_open():
    skills = _Skills({"files.find_open": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("open the file called budget")
    assert ("files.find_open", {"query": "budget"}) in skills.executed


def test_open_app_is_not_hijacked_by_the_file_route():
    skills = _Skills({"app.open": _Skill(), "files.find_open": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("open spotify")
    assert ("app.open", {"name": "spotify"}) in skills.executed
    assert all(name != "files.find_open" for name, _ in skills.executed)


# ── USER_APPROVAL commands ACT via a two-step voice confirm ───────────────────

def test_close_app_is_a_two_step_confirm_that_then_runs():
    skills = _Skills({"app.close": _Skill(Permission.USER_APPROVAL)})
    cloud = _CloudSpy()
    bridge = _bridge(skills, cloud)
    r1 = bridge.think("close chrome")
    assert skills.executed == []                   # not yet — waits for confirm
    assert cloud.called == 0                       # never explained/essayed
    assert "confirm" in r1.answer.lower() and "close chrome" in r1.answer.lower()
    r2 = bridge.think("confirm")
    assert skills.executed == [("app.close", {"name": "chrome"})]   # it RAN
    assert r2.answer == "Done."


def test_a_stray_phrase_cancels_a_pending_command_confirm():
    skills = _Skills({"app.close": _Skill(Permission.USER_APPROVAL)})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("close chrome")                    # arms the confirm
    bridge.think("what's the time")                 # NOT a confirm
    bridge.think("confirm")                         # too late — nothing pending
    assert skills.executed == []                    # never ran


def test_type_command_confirms_then_runs():
    skills = _Skills({"input.type_text": _Skill(Permission.USER_APPROVAL)})
    bridge = _bridge(skills, _CloudSpy())
    assert "confirm" in bridge.think("type hello world").answer.lower()
    bridge.think("confirm")
    assert skills.executed == [("input.type_text", {"text": "hello world"})]


def test_click_a_label_confirms_then_runs_the_aim_faculty():
    skills = _Skills({"screen.click_text": _Skill(Permission.USER_APPROVAL)})
    bridge = _bridge(skills, _CloudSpy())
    r1 = bridge.think("click the Save button")
    assert skills.executed == []                    # waits for confirm (it's a click)
    assert "confirm" in r1.answer.lower() and "save" in r1.answer.lower()
    bridge.think("confirm")
    assert skills.executed == [("screen.click_text", {"query": "Save"})]


# ── multi-step: chain everyday actions into one plan ──────────────────────────

def test_multistep_all_safe_runs_in_order_without_confirm():
    skills = _Skills({"files.find_open": _Skill(), "app.open": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    r = bridge.think("open notes.txt and open spotify")
    assert [n for n, _ in skills.executed] == ["files.find_open", "app.open"]
    assert skills.executed[0][1] == {"query": "notes.txt"}
    assert skills.executed[1][1] == {"name": "spotify"}
    assert "done" in r.answer.lower()


def test_multistep_with_a_click_confirms_the_whole_plan_then_runs():
    skills = _Skills({"files.find_open": _Skill(),
                      "screen.click_text": _Skill(Permission.USER_APPROVAL)})
    bridge = _bridge(skills, _CloudSpy())
    r1 = bridge.think("open report.pdf and click Print")
    assert skills.executed == []                         # one confirm for the whole plan
    assert "confirm" in r1.answer.lower()
    assert "open report.pdf" in r1.answer.lower() and "print" in r1.answer.lower()
    bridge.think("confirm")
    assert [n for n, _ in skills.executed] == ["files.find_open", "screen.click_text"]
    assert skills.executed[1][1] == {"query": "Print"}


def test_a_filename_containing_and_is_not_split_into_a_chain():
    skills = _Skills({"files.find_open": _Skill(), "app.open": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("open the sales and marketing file")
    names = [n for n, _ in skills.executed]
    assert names == ["files.find_open"]                 # whole thing, not mis-chained


# ── point-and-teach icons: learn by name, then click by name ──────────────────

def test_remember_this_as_icon_teaches_it_immediately():
    skills = _Skills({"screen.teach_icon": _Skill()})       # SAFE → runs at once
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("remember this as the settings icon")
    assert ("screen.teach_icon", {"name": "settings"}) in skills.executed


def test_click_the_x_icon_confirms_then_clicks_by_name():
    skills = _Skills({"screen.click_icon": _Skill(Permission.USER_APPROVAL)})
    bridge = _bridge(skills, _CloudSpy())
    r1 = bridge.think("click the settings icon")
    assert skills.executed == []                             # waits for confirm
    assert "confirm" in r1.answer.lower() and "settings" in r1.answer.lower()
    bridge.think("confirm")
    assert skills.executed == [("screen.click_icon", {"name": "settings"})]


def test_click_a_text_label_is_not_treated_as_an_icon():
    skills = _Skills({"screen.click_text": _Skill(Permission.USER_APPROVAL),
                      "screen.click_icon": _Skill(Permission.USER_APPROVAL)})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("click Save")
    bridge.think("confirm")
    assert [n for n, _ in skills.executed] == ["screen.click_text"]


def test_stop_playing_the_music_pauses():
    skills = _Skills({"media.play_pause": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("stop playing the music")            # "playing" never matched \bplay\b before
    assert ("media.play_pause", {}) in skills.executed


def test_describe_image_routes_to_vision_describe():
    skills = _Skills({"vision.describe": _Skill()})     # SAFE (read-only) → runs
    bridge = _bridge(skills, _CloudSpy())
    bridge.think(r"what's in this picture C:\pics\holiday.jpg")
    assert ("vision.describe", {"path": r"C:\pics\holiday.jpg"}) in skills.executed


def test_admin_commands_are_refused_never_confirmable():
    skills = _Skills({})
    cloud = _CloudSpy()
    bridge = _bridge(skills, cloud)
    for cmd in ("restart the computer", "shut down", "run shell rm -rf /"):
        r = bridge.think(cmd)
        assert "administrator" in r.answer.lower()
        assert cloud.called == 0
    assert skills.executed == []                    # nothing ran


# ── unknown device commands decline honestly (no essay) ───────────────────────

def test_unknown_device_command_declines_in_one_sentence():
    cloud = _CloudSpy()
    bridge = _bridge(_Skills({}), cloud)
    resp = bridge.think("eject the usb drive")
    assert cloud.called == 0                       # a command never hits cloud
    assert "don't have an action" in resp.answer
    assert "command:unavailable" in bridge._decision_log.rows[-1]["route"]


# ── understanding stays understanding ─────────────────────────────────────────

def test_questions_still_take_the_reasoning_path():
    cloud = _CloudSpy()
    bridge = _bridge(_Skills({}), cloud)
    resp = bridge.think("how do I open notepad on windows?")
    assert cloud.called == 1                       # a question MAY be explained
    assert resp.answer == "a long explanation …"


def test_speech_act_verbs_are_not_gated():
    cloud = _CloudSpy()
    bridge = _bridge(_Skills({}), cloud)
    bridge.think("explain how volcanoes form")
    bridge.think("tell me about the roman empire")
    assert cloud.called == 2                       # understanding untouched
