"""Bank commands survive the round trip: typed -> plan file -> flown.

A bank row is (start s, end s, bank deg), held while start <= t <= end.  Four
ways a typed or saved bank used to be lost without a word, each pinned here:

  * a row the dialog could not parse (no end time, '10°', '10,5', a Unicode
    minus) was dropped at Save, and an empty schedule was written over the
    saved one;
  * the sidebar's hidden store formatted rows with :.0f, and the next Run or
    Edit wrote the rounded values back (10.5 -> 10, 0.4 -> 0);
  * the plan dropdown's typeahead restored the list it saw at bind time, so
    after one pick the Reentry Plan dropdown offered only '(default)';
  * rebuilding a plan over the raw file carried retired keys forward.

GUI tests point every plan path at a temporary folder: the app would
otherwise write into the user's ~/Documents/Thrusty."""
import json

import pytest

import booster_models as mm


# ── core: parsing typed rows ────────────────────────────────────────────────

def test_complete_rows_parse_and_blank_rows_are_skipped():
    rows = [("591", "700", "10"), ("", "", ""), ("700", "800", "-20")]
    assert mm.bank_schedule_from_rows(rows) == [[591.0, 700.0, 10.0],
                                                [700.0, 800.0, -20.0]]
    assert mm.bank_schedule_from_rows([("", " ", None)] * 3) == []


def test_what_people_type_is_accepted():
    """A degree sign, the Unicode minus and a lone decimal comma are what a
    keyboard or a pasted table produces; each used to drop its row."""
    rows = [("600,5", "700.25", "10°"), ("700.25", "800", "−20 °")]
    assert mm.bank_schedule_from_rows(rows) == [[600.5, 700.25, 10.0],
                                                [700.25, 800.0, -20.0]]


@pytest.mark.parametrize("row, words", [
    (("591", "", "10"), ["Bank #1", "end time"]),          # the turn stop
    (("", "700", ""), ["Bank #1", "start time", "bank angle"]),
    (("591", "700", "ten"), ["Bank #1", "bank angle", "'ten'"]),
    (("700", "700", "10"), ["Bank #1", "after the start"]),
    (("700", "600", "10"), ["Bank #1", "after the start"]),
    (("591", "inf", "10"), ["Bank #1", "finite"]),
    (("1,100", "1,400", "20"), ["Bank #1", "ambiguous", "1100", "1.1"]),
])
def test_an_unflyable_row_is_refused_by_name(row, words):
    with pytest.raises(ValueError) as e:
        mm.bank_schedule_from_rows([row])
    assert all(w in str(e.value) for w in words), str(e.value)
    with pytest.raises(ValueError) as e:                      # numbered by row
        mm.bank_schedule_from_rows([("1", "2", "3"), row])
    assert "Bank #2" in str(e.value)


# ── core: the one write drops retired keys, keeps everything accounted ──────

def test_save_reentry_plan_writes_only_accounted_keys(tmp_path):
    rp = dict(mm.extract_reentry_plan(mm.ROParams(name="X", mass_kg=100.0,
                                                  beta_kg_m2=5000.0)),
              glider_bank_schedule=[[600.5, 700.25, 10.5]],
              source="a citation", notes="why",
              separation_mode="separating_ro",         # retired: DERIVED now
              glider_beta_entry_kg_m2=0.0)             # retired: read by nothing
    d = json.loads(open(mm.save_reentry_plan("X", rp, tmp_path)).read())
    assert "separation_mode" not in d and "glider_beta_entry_kg_m2" not in d
    assert d["source"] == "a citation" and d["notes"] == "why"
    assert d["glider_bank_schedule"] == [[600.5, 700.25, 10.5]]
    assert set(d) <= mm.REENTRY_PLAN_FILE_KEYS
    v = json.loads(open(mm.save_reentry_plan("X", rp, tmp_path, plan="V")).read())
    assert v["name"] == "V" and v["reentry_object"] == "X"
    assert "separation_mode" not in v


# ── GUI ─────────────────────────────────────────────────────────────────────

tk = pytest.importorskip("tkinter", reason="no Tk in this interpreter")


@pytest.fixture(scope="module")
def app():
    import matplotlib
    matplotlib.use("Agg")
    import thrusty
    try:
        a = thrusty.BoosterFlyoutApp()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    a.withdraw()
    yield a
    a.destroy()


@pytest.fixture
def plans(tmp_path, monkeypatch, app):
    """Every path the reentry-plan flows write, pointed at tmp_path, and the
    messageboxes recorded instead of shown."""
    import thrusty
    from tkinter import messagebox
    monkeypatch.setattr(thrusty, "_REENTRY_PLAN_LIBRARY_PATH", tmp_path)
    monkeypatch.setattr(thrusty, "_ACTIVE_REENTRY_PLANS_PATH",
                        tmp_path / "active_reentry_plans.json")
    monkeypatch.setattr(mm, "USER_REENTRY_PLAN_DIRS", [str(tmp_path)])
    shown = []
    for fn in ("showerror", "showinfo", "showwarning"):
        monkeypatch.setattr(messagebox, fn,
                            lambda *a, _fn=fn, **k: shown.append((_fn, a)))
    monkeypatch.setattr(app, "wait_window", lambda w=None: None)
    app._ro_main_var.set("C-HGB")
    app._on_ro_selected_main()
    app.update()
    return tmp_path, shown


def _edit(app, monkeypatch, rows):
    """Open Edit Reentry Plan…, type `rows` into the bank grid, press Save.
    Returns (rows the dialog opened with, the dialog)."""
    import thrusty
    seen = {}
    real = next(c for c in thrusty.ReentryPlanDialog.__mro__
                if not c.__dict__.get("_driven"))   # not an earlier stand-in

    class Driven(real):
        _driven = True

        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            seen["opened"] = [[bv[c].get() for c in ("start", "end", "bank")]
                              for bv in self._bank_vars]
            for bv, row in zip(self._bank_vars, rows):
                for c, v in zip(("start", "end", "bank"), row):
                    bv[c].set(v)
            seen["dlg"] = self
            self._save()

    monkeypatch.setattr(thrusty, "ReentryPlanDialog", Driven)
    app._edit_reentry_plan_main()
    dlg = seen["dlg"]
    if dlg.winfo_exists():                    # refused: still open — close it
        dlg.destroy()
    return seen["opened"], dlg


def _file_bank(folder):
    return json.loads((folder / "C-HGB.reentryplan.json").read_text())[
        "glider_bank_schedule"]


def test_a_row_without_its_turn_stop_is_refused_not_dropped(app, plans,
                                                            monkeypatch):
    folder, shown = plans
    good = [["600.5", "700.25", "10.5"], ["700.25", "800", "-0.4"]]
    _edit(app, monkeypatch, good)
    assert _file_bank(folder) == [[600.5, 700.25, 10.5], [700.25, 800.0, -0.4]]
    assert shown == []

    # the user's case: a start and a bank, no end time
    _, dlg = _edit(app, monkeypatch, [["591", "", "20"], ["", "", ""]])
    assert dlg.result is None                       # nothing merged or saved
    assert [fn for fn, _ in shown] == ["showerror"]
    assert "Bank #1" in shown[0][1][1] and "end time" in shown[0][1][1]
    assert _file_bank(folder) == [[600.5, 700.25, 10.5], [700.25, 800.0, -0.4]]


def test_a_saved_fractional_bank_survives_run_and_reopen(app, plans,
                                                         monkeypatch):
    """The hidden sidebar store used to round to whole numbers and the next
    write-through (Run, Max Range, Plan Orbit, or just opening Edit…) wrote
    the rounded rows back."""
    folder, _ = plans
    exact = [[600.5, 700.25, 10.5], [700.25, 800.6, -0.4]]
    _edit(app, monkeypatch, [[repr(v) for v in r] for r in exact])
    assert _file_bank(folder) == exact
    app._snapshot_reentry_plan()                    # what Run does first
    assert _file_bank(folder) == exact
    opened, _ = _edit(app, monkeypatch, [])          # re-open, change nothing
    assert [[float(c) for c in r] for r in opened[:2]] == exact
    assert _file_bank(folder) == exact


def test_the_plan_dropdown_keeps_values_added_after_binding(app):
    """The typeahead captured the values at bind time and wrote them back on
    every pick, so a dropdown refreshed later (plan variants) collapsed to
    what it first held.  It must read the list live.  (The typed-prefix
    path needs keyboard focus, which a withdrawn test window cannot take; it
    reads the same live list.)"""
    from tkinter import ttk
    import thrusty
    cb = ttk.Combobox(app, values=["(default)"])
    thrusty._bind_typeahead(cb)
    try:
        cb["values"] = ["(default)", "C-HGB glide", "CHGB ballistic"]
        cb.set("C-HGB glide")
        cb.event_generate("<<ComboboxSelected>>")
        app.update()
        assert list(cb["values"]) == ["(default)", "C-HGB glide",
                                      "CHGB ballistic"]
        assert cb.get() == "C-HGB glide"
    finally:
        cb.destroy()


def test_an_analytic_plan_saves_without_judging_a_grid_it_does_not_show(
        app, plans, monkeypatch):
    """An analytic law has no bank grid in the editor, so its stored schedule
    is kept exactly -- even a row the grid would refuse -- rather than every
    Save being refused over rows the user cannot see or fix."""
    folder, shown = plans
    stored = json.loads(open("reentry_plans/C-HGB.reentryplan.json").read())
    stored.update(glider_guidance="equilibrium_glide",
                  glider_bank_schedule=[[700.0, 600.0, 10.0]])
    (folder / "C-HGB.reentryplan.json").write_text(json.dumps(stored))
    app._on_ro_selected_main()
    app.update()
    _, dlg = _edit(app, monkeypatch, [])
    assert dlg.result is not None and "glider_bank_schedule" not in dlg.result
    assert shown == []
    assert _file_bank(folder) == [[700.0, 600.0, 10.0]]


def test_clicking_away_from_a_typed_name_does_not_select_it(app):
    """Typing is not selecting.  Clicking away used to snap the text to its
    best match without <<ComboboxSelected>>, so the field named a plan that was
    not active and the next Run saved the panel over it.  An abandoned edit now
    goes back to what was last committed; Enter still selects, with the
    event; and an exact name beats a longer one that starts with it."""
    from types import SimpleNamespace
    from tkinter import ttk
    import thrusty
    cb = ttk.Combobox(app, values=["(default)", "AUR (2)", "AUR simple"])
    h = thrusty._bind_typeahead(cb)
    fired = []
    cb.bind("<<ComboboxSelected>>", lambda e: fired.append(cb.get()), add="+")

    def key(keysym, text=None):
        """One keystroke as Tk delivers it: press, the edit, release."""
        h["key_press"](SimpleNamespace(keysym=keysym))
        if text is not None:
            cb.set(text)
        h["on_key"](SimpleNamespace(keysym=keysym))

    try:
        cb.set("AUR (2)")
        cb.event_generate("<<ComboboxSelected>>")
        app.update()
        key("s", "AUR s")                                # typed, not committed
        h["commit_silent"]()                             # focus moved away
        assert cb.get() == "AUR (2)" and fired == ["AUR (2)"]

        key("s", "AUR s")
        h["commit_fire"]()                               # Enter commits
        app.update()
        assert cb.get() == "AUR simple" and fired[-1] == "AUR simple"
        h["commit_silent"]()                             # nothing left to undo
        assert cb.get() == "AUR simple"

        cb["values"] = ["(default)", "Orbital 400 km", "orbital"]
        key("l", "orbital")
        h["commit_fire"]()
        assert cb.get() == "orbital"
    finally:
        cb.destroy()


def test_a_value_the_app_sets_is_never_reverted(app):
    """The app switches a dropdown itself -- Max Range selects 'max-range', a
    booster change refreshes the plan list -- with no <<ComboboxSelected>>.
    A later key that edits nothing (an arrow, Cmd+C) is not an edit, and an
    abandoned edit goes back to what was on screen when it began, not to an
    older selection; a value the app sets during an edit stands."""
    from types import SimpleNamespace
    from tkinter import ttk
    import thrusty
    cb = ttk.Combobox(app, values=["(default)", "max-range", "orbital"])
    h = thrusty._bind_typeahead(cb)

    def key(keysym, text=None):
        h["key_press"](SimpleNamespace(keysym=keysym))
        if text is not None:
            cb.set(text)
        h["on_key"](SimpleNamespace(keysym=keysym))

    try:
        cb.set("(default)")
        cb.event_generate("<<ComboboxSelected>>")
        app.update()
        cb.set("max-range")                  # the app, with no event
        key("Right")                         # edits nothing
        h["commit_silent"]()
        assert cb.get() == "max-range"

        key("x", "max-rangex")               # an abandoned edit
        h["commit_silent"]()
        assert cb.get() == "max-range"       # not '(default)'

        key("o", "o")                        # an edit in progress, then
        cb.set("orbital")                    # the app sets a value
        h["commit_silent"]()
        assert cb.get() == "orbital"
    finally:
        cb.destroy()
