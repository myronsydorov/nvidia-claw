"""The static gate: only watcher_runtime imports, no escape hatches, declared URLs only."""

import pytest
from warden.adapters import ics_calendar, parcel_dhl, web_diff
from warden.compiler.gate import MAX_BYTES, GateError, check

PAGE = "https://www.example.org/tickets"
WEB = web_diff.declare(url=PAGE, why="check this page for changes")
DHL = parcel_dhl.ADAPTER

GOOD = f'''from watcher_runtime import harness
from watcher_runtime.adapters import web_diff

URL = "{PAGE}"
try:
    page = web_diff.fetch(URL, None)
except Exception:
    harness.fail("I couldn't read the page.")
else:
    state = harness.load_state()
    harness.save_state({{"hash": page["content_hash"]}})
    harness.emit("ok", "No change.", "example.org")
'''


def gate(code: str, adapters: list = [WEB]) -> None:  # type: ignore[type-arg]  # noqa: B006
    check(code, [a.name for a in adapters], [e for a in adapters for e in a.endpoints])


def problems(code: str, adapters: list = [WEB]) -> str:  # type: ignore[type-arg]  # noqa: B006
    with pytest.raises(GateError) as info:
        gate(code, adapters)
    return "\n".join(info.value.problems)


def test_good_watcher_passes() -> None:
    gate(GOOD)


def test_other_import_styles_pass() -> None:
    gate(
        "import watcher_runtime.adapters.parcel_dhl as dhl\n"
        "from watcher_runtime.harness import emit, now\n"
        "emit('ok', dhl.fetch('1')['status'], 'DHL', {'at': now().isoformat()})\n",
        [DHL],
    )


PREAMBLE = "from watcher_runtime import harness\nharness.emit('ok', 'x', 'y')\n"


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ("import subprocess", "'subprocess' is not allowed"),
        ("import os\nos.system('id')", "'os' is not allowed"),
        ("from os import system", "import from 'os' is not allowed"),
        ("import socket", "'socket' is not allowed"),
        ("import httpx2", "'httpx2' is not allowed"),
        ("import json", "'json' is not allowed"),
        ("from watcher_runtime.adapters import parcel_dhl", "not allowed"),  # not declared
        ("import watcher_runtime.harness", "as <name>"),
        ("from watcher_runtime.harness import *", "star imports"),
        ("from . import x", "relative imports"),
        ("eval('1')", "'eval' is not allowed"),
        ("exec('x=1')", "'exec' is not allowed"),
        ("compile('1', 'f', 'eval')", "'compile' is not allowed"),
        ("__import__('os')", "'__import__' is not allowed"),
        ("getattr(harness, 'emit')", "'getattr' is not allowed"),
        ("f = vars()", "'vars' is not allowed"),
        ("x = ().__class__.__bases__", "'__class__' is not allowed"),
        ("x = '{0.__class__}'.format(1)", "may not contain '__'"),
        ("x = __builtins__", "'__builtins__' is not allowed"),
        ("from watcher_runtime.adapters import web_diff\nweb_diff.httpx.post('u')", "httpx"),
        ("from watcher_runtime.adapters import web_diff\nweb_diff._excerpt('u')", "_excerpt"),
        ("harness.os.system('id')", "harness.os is not part of the allowed API"),
        ("from watcher_runtime.harness import _STATE_PATH", "not part of the allowed API"),
        ("h = harness", "may only be used as"),
        ("open('/etc/passwd', 'w').write('x')", "only allowed with a literal path under /tmp/"),
        ("open('/tmp/../etc/x', 'w')", "/tmp/"),
        ("p = '/w/run.py'\nopen(p, 'w')", "/tmp/"),
        ("o = open", "open() may only be called directly"),
        ("x = 'https://evil.example.com/steal'", "host 'evil.example.com' is not declared"),
        ("x = 'https://www.example.org/admin'", "path '/admin'"),
        ("x = 'http://www.example.org/tickets'", "only https"),
    ],
)
def test_forbidden_constructs_are_rejected(snippet: str, expected: str) -> None:
    assert expected in problems(PREAMBLE + snippet + "\n")


# Security review T-09: each of these passed the first version of the gate.
@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        (
            "match harness.now:\n    case object(__globals__=g):\n        g['os'].system('id')",
            "match statements are not allowed",
        ),
        ("b = (i for i in [1]).gi_frame.f_builtins", "attribute 'gi_frame' is not allowed"),
        (
            "s = ('{0.' + '_' + '_globals_' + '_[os].environ}').format(harness.now)",
            "attribute 'format' is not allowed",
        ),
        ("s = '{0}'.format_map({})", "attribute 'format_map' is not allowed"),
        ("def __init_subclass__(cls):\n    pass", "identifier '__init_subclass__'"),
        ("def f(_x):\n    return _x", "identifier '_x'"),
        ("harness.emit(_x=1, status='ok', summary='s', source='s')", "identifier '_x'"),
        ("class C:\n    pass", "class definitions are not allowed"),
        ("u = chr(95) * 2", "'chr' is not allowed"),
        ("t = type(harness)", "'type' is not allowed"),
        ("o = object", "'object' is not allowed"),
        ("print('extra line on stdout')", "'print' is not allowed"),
        ("m = [].mro", "attribute 'mro' is not allowed"),
        ("from watcher_runtime.harness import secret", "not part of the allowed API"),
        ("k = harness.secret('NVIDIA_API_KEY')", "harness.secret is not part of the allowed API"),
        ("def f():\n    from watcher_runtime import harness as h\n    return h", "top level"),
    ],
)
def test_review_bypasses_are_rejected(snippet: str, expected: str) -> None:
    assert expected in problems(PREAMBLE + snippet + "\n")


def test_a_module_used_before_its_import_is_still_checked() -> None:
    code = (
        "def f():\n    return harness\n"
        "from watcher_runtime import harness\n"
        "harness.emit('ok', 'x', 'y')\n"
    )
    assert "may only be used as" in problems(code)


def test_ordinary_watcher_idioms_still_pass() -> None:
    gate(
        PREAMBLE
        + "state = harness.load_state()\n"
        + "items = sorted(state.get('items', []), key=lambda d: d.get('when') or '')\n"
        + "late = [d for d in items if (d.get('delay_s') or 0) > 600]\n"
        + "names = ', '.join(str(d.get('line', '')).strip().upper() for d in late)\n"
        + "hours = harness.hours_until('2026-10-02T16:00:00Z')\n"
        + "day = harness.now().date().isoformat()\n"
        + "summary = f'{len(late)} late ({names}) {hours:.0f}h left on {day}'\n"
    )


def test_open_under_tmp_is_allowed() -> None:
    gate(PREAMBLE + "with open('/tmp/notes.json', 'w') as fh:\n    fh.write('{}')\n")


def test_syntax_error_reports_line() -> None:
    assert "syntax error on line 2" in problems("x = 1\nif:\n")


def test_size_limit() -> None:
    assert f"larger than {MAX_BYTES} bytes" in problems(PREAMBLE + "# " + "x" * MAX_BYTES + "\n")


def test_must_emit() -> None:
    code = "from watcher_runtime import harness\nx = harness.now()\n"
    assert "never calls harness.emit" in problems(code)


GCAL = (
    "https://calendar.google.com/calendar/ical/"
    "de.german%23holiday%40group.v.calendar.google.com/public/basic.ics"
)


def test_a_percent_encoded_url_passes_against_its_canonical_declaration() -> None:
    # T-04: declared as '/…/de.german%23holiday@group…' (OpenShell's canonical form).
    cal = ics_calendar.declare(url=GCAL, why="check the school calendar")
    gate(
        "from watcher_runtime import harness\n"
        "from watcher_runtime.adapters import ics_calendar\n"
        f'events = ics_calendar.fetch("{GCAL}")\n'
        "harness.emit('ok', 'fine', 'calendar')\n",
        [cal],
    )


@pytest.mark.parametrize("path", ["/a%2F..%2Fadmin", "/tickets/*", "/x/../tickets", "/tickets;x"])
def test_a_url_whose_path_cannot_be_declared_is_refused(path: str) -> None:
    url = f"https://www.example.org{path}"
    found = problems(f"from watcher_runtime import harness\nharness.emit('ok', '{url}', 'y')\n")
    assert "can't be declared safely" in found
