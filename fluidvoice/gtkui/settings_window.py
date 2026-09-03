"""Settings window — Adw.PreferencesWindow with one page per section
(the macOS app's Settings counterpart).

Covers every key the daemon's set-config validates. Saving goes through
the socket (live cfg + hot-apply); with the daemon down it degrades to
file-only mode (the save row and the load toast say so). Unsaved changes
are tracked: the Save row / Ctrl+S apply, closing with pending changes
asks first.
"""
from __future__ import annotations

import threading

from gi.repository import Adw, Gdk, GLib, Gtk

from .. import __version__ as APP_VERSION
from .. import backends, model_catalog
from ..config import DEFAULTS
from .client import Client

# GDK keyval name -> friendly keysym the config expects (where they differ)
_KEY_REMAP = {"Control_L": "Left_Control", "Control_R": "Right_Control",
              "Alt_L": "Left_Alt", "Alt_R": "Right_Alt",
              "Shift_L": "Left_Shift", "Shift_R": "Right_Shift",
              "Super_L": "Left_Super", "Super_R": "Right_Super"}

# Whisper language codes offered in the picker (validation accepts any code;
# a saved code not in this list is appended as an extra option on load)
LANGUAGES = ["en", "de", "es", "fr", "it", "nl", "pl", "pt", "ru", "uk",
             "sl", "sr", "hr", "bs", "cs", "sk", "sv", "da", "fi", "no",
             "hu", "ro", "bg", "el", "tr", "zh", "ja", "ko", "ar", "hi"]


class _SwitchProxy:
    """Adapter so plain Gtk.Switch rows (inside expanders) load/collect like
    Adw.SwitchRow through the same field registry."""

    def __init__(self, switch: Gtk.Switch, title: str, subtitle: str = ""):
        self.switch = switch
        self.title = title
        self.subtitle = subtitle

    def set_active(self, v: bool) -> None:
        self.switch.set_active(v)

    def get_active(self) -> bool:
        return self.switch.get_active()


class _ListProxy:
    """EntryRow-backed list<string> (comma-separated) for the field registry."""

    def __init__(self, row: Adw.EntryRow):
        self.row = row

    def set_value(self, values) -> None:
        self.row.set_text(", ".join(values or []))

    def get_value(self) -> list:
        return [v.strip() for v in self.row.get_text().split(",")
                if v.strip()]


class _InstructionRow(Adw.PreferencesRow):
    """A preferences-compatible row that hosts the instructions TextView."""

    def __init__(self, text_view: Gtk.TextView):
        super().__init__(title="Instructions")
        sw = Gtk.ScrolledWindow(child=text_view, hexpand=True,
                                height_request=90,
                                propagate_natural_height=True)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                      margin_start=14, margin_end=14, margin_bottom=8)
        box.append(sw)
        self.set_child(box)


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, application=None, client=None):
        super().__init__(application=application, title="Settings",
                         default_width=680, default_height=680)
        self.c = client or Client()
        self.cfg: dict = {}
        self._from_daemon = False
        self._loading = False
        self._dirty = False
        self._rows: dict[tuple[str, str], object] = {}
        self._combo_values: dict[tuple[str, str], list] = {}
        self._rule_rows: list[dict] = []  # per-app prompt editors
        self._dict_rows: list[dict] = []  # custom-dictionary editors
        self._save_groups: list[Adw.PreferencesGroup] = []
        self._save_rows: list[Adw.ActionRow] = []
        self._model_rows: list[Adw.ActionRow] = []
        self._mod_toggles: dict[str, Gtk.ToggleButton] = {}

        self._build_general()
        self._build_models()
        self._build_ai()
        self._build_dictation()
        self._build_history_page()
        self._build_about()

        self.install_action("settings.save", None,
                            lambda w, _n, _p: w.save())
        ctrl = Gtk.ShortcutController()
        ctrl.add_shortcut(Gtk.Shortcut(
            trigger=Gtk.ShortcutTrigger.parse_string("<primary>s"),
            action=Gtk.NamedAction.new("settings.save")))
        self.add_controller(ctrl)
        self.connect("close-request", self._on_close_request)

        self._load()

    # -- save / discard bar (bottom of every content page) ----------------------

    def _save_group(self) -> Adw.PreferencesGroup:
        grp = Adw.PreferencesGroup()
        row = Adw.ActionRow(title=self._save_title("Changes are saved"),
                            subtitle="")
        self._save_rows.append(row)
        save_btn = Gtk.Button(label="Save", css_classes=["suggested-action"])
        save_btn.set_valign(Gtk.Align.CENTER)
        save_btn.connect("clicked", lambda *_: self.save())
        discard_btn = Gtk.Button(label="Discard", css_classes=["flat"])
        discard_btn.set_valign(Gtk.Align.CENTER)
        discard_btn.connect("clicked", lambda *_: self._load())
        row.add_suffix(discard_btn)
        row.add_suffix(save_btn)
        grp.add(row)
        self._save_groups.append(grp)
        return grp

    def _save_title(self, base: str) -> str:
        suffix = "" if self._from_daemon else " — daemon offline, saving to file"
        return base + (" · UNSAVED" if self._dirty else "") + suffix

    def _sync_save_rows(self) -> None:
        for row in self._save_rows:
            row.set_title(self._save_title("Changes are saved"))

    # -- field registry -----------------------------------------------------------

    def _touch(self) -> None:
        if not self._loading and not self._dirty:
            self._dirty = True
            self._sync_save_rows()

    def _switch(self, section, key, title, subtitle="") -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.connect("notify::active", lambda *_: self._touch())
        self._rows[(section, key)] = row
        return row

    def _entry(self, section, key, title, capture=False) -> Adw.EntryRow:
        row = Adw.EntryRow(title=title)
        row.connect("changed", lambda *_: self._touch())
        self._rows[(section, key)] = row
        if capture:
            btn = Gtk.Button(icon_name="media-record-symbolic",
                             css_classes=["flat"], tooltip_text="Press a key…")
            btn.connect("clicked", self._start_capture, row)
            row.add_suffix(btn)
        return row

    def _combo(self, section, key, title, values,
               subtitle="") -> Adw.ComboRow:
        """values: list of (label, config_value)."""
        row = Adw.ComboRow(title=title, subtitle=subtitle)
        model = Gtk.StringList()
        for label, _v in values:
            model.append(label)
        row.set_model(model)
        row.connect("notify::selected", lambda *_: self._touch())
        self._rows[(section, key)] = row
        self._combo_values[(section, key)] = [v for _l, v in values]
        return row

    def _refill_combo(self, section: str, key: str, values) -> None:
        """Rebuild a combo's options (e.g. to append a saved unknown value)."""
        model = Gtk.StringList()
        for label, _v in values:
            model.append(label)
        self._rows[(section, key)].set_model(model)
        self._combo_values[(section, key)] = [v for _l, v in values]

    def _spin(self, section, key, title, lo, hi, step, digits=0,
              subtitle="") -> Adw.SpinRow:
        adj = Gtk.Adjustment(value=lo, lower=lo, upper=hi, step_increment=step)
        row = Adw.SpinRow(title=title, subtitle=subtitle, adjustment=adj,
                          digits=digits)
        row.connect("notify::value", lambda *_: self._touch())
        self._rows[(section, key)] = row
        return row

    def _plain_switch_row(self, section, key, title) -> Adw.ActionRow:
        """Gtk.Switch inside an ActionRow (for use inside ExpanderRows)."""
        row = Adw.ActionRow(title=title)
        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        switch.connect("notify::active", lambda *_: self._touch())
        self._rows[(section, key)] = _SwitchProxy(switch, title)
        row.add_suffix(switch)
        return row

    # -- load / collect / save ------------------------------------------------------

    def _load(self) -> None:
        self._loading = True
        self.cfg, self._from_daemon = self.c.get_config()
        if not self._from_daemon and not self._loading_first_done:
            self._loading_first_done = True
            GLib.idle_add(self.toast,
                          "Daemon offline — file-only mode; changes apply on "
                          "next daemon start", 6)
        self._fill_mics()
        lang = str(self.cfg.get("general", {}).get("language", "auto"))
        if lang != "auto" and lang not in LANGUAGES:
            # a saved code outside the common list stays selectable
            self._refill_combo("general", "language",
                               [("auto (detect)", "auto")]
                               + [(c, c) for c in LANGUAGES]
                               + [(f"{lang} (saved)", lang)])
        for (sec, key), row in self._rows.items():
            val = self.cfg.get(sec, {}).get(key, _default(sec, key))
            if isinstance(row, _SwitchProxy):
                row.set_active(bool(val))
            elif isinstance(row, Adw.SwitchRow):
                row.set_active(bool(val))
            elif isinstance(row, _ListProxy):
                row.set_value(val)
            elif isinstance(row, Adw.EntryRow):
                row.set_text("" if val is None else str(val))
            elif isinstance(row, Adw.ComboRow):
                values = self._combo_values[(sec, key)]
                idx = values.index(val) if val in values else 0
                row.set_selected(idx)
            elif isinstance(row, Adw.SpinRow):
                row.set_value(float(val))
        for mod, tb in self._mod_toggles.items():
            tb.set_active(mod in (self.cfg.get("hotkey", {})
                                  .get("modifiers") or []))
        self._load_rules(self.cfg.get("ai", {}).get("per_app_prompts") or [])
        self._load_dictionary(self.cfg.get("processing", {}).get("dictionary")
                              or [])
        self._dirty = False
        self._loading = False
        self._sync_save_rows()
        self._refresh_models()

    _loading_first_done = False

    def _collect(self) -> dict:
        body: dict = {}
        for (sec, key), row in self._rows.items():
            if isinstance(row, _SwitchProxy):
                val = row.get_active()
            elif isinstance(row, Adw.SwitchRow):
                val = row.get_active()
            elif isinstance(row, _ListProxy):
                val = row.get_value()
            elif isinstance(row, Adw.EntryRow):
                val = row.get_text().strip()
                if not val:
                    continue  # empty optional strings keep the saved value
            elif isinstance(row, Adw.ComboRow):
                val = self._combo_values[(sec, key)][row.get_selected()]
            elif isinstance(row, Adw.SpinRow):
                val = (int(row.get_value()) if row.get_digits() == 0
                       else round(row.get_value(), 4))
            else:
                continue
            body.setdefault(sec, {})[key] = val
        body.setdefault("hotkey", {})["modifiers"] = [
            m for m, tb in self._mod_toggles.items() if tb.get_active()]
        rules = self._collect_rules()
        if rules is not None:
            body.setdefault("ai", {})["per_app_prompts"] = rules
        body.setdefault("processing", {})["dictionary"] = \
            self._collect_dictionary()
        return body

    def save(self) -> bool:
        body = self._collect()
        resp = self.c.set_config(body)
        changed = resp.get("changed") or []
        rejected = resp.get("rejected") or []
        errors = resp.get("errors") or []
        restart = resp.get("restart_required") or []
        if rejected:
            self.toast(f"Rejected (bad values): {', '.join(rejected)}")
        elif errors:
            self.toast(f"Not fully applied: {'; '.join(errors)}")
        elif changed:
            msg = f"Saved {len(changed)} change{'' if len(changed) == 1 else 's'}"
            if restart:
                msg += f" — restart daemon for: {', '.join(restart)}"
            self.toast(msg)
        else:
            self.toast("No changes")
        self._load()  # resync from the daemon/file
        return True

    def toast(self, text: str, timeout: int = 5) -> None:
        super().add_toast(Adw.Toast(title=text, timeout=timeout))

    def _on_close_request(self, *_args) -> bool:
        if not self._dirty:
            return False  # allow close
        dlg = Adw.MessageDialog(transient_for=self, modal=True,
                                heading="Discard unsaved changes?",
                                body="Changes that were not saved will be lost.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("discard", "Discard")
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)

        def responded(_dlg, response):
            if response == "discard":
                self._dirty = False
                self.close()
        dlg.connect("response", responded)
        dlg.present()
        return True  # block close until answered

    # -- key capture ------------------------------------------------------------------

    def _start_capture(self, btn, row: Adw.EntryRow) -> None:
        ctrl = Gtk.EventControllerKey()
        self.add_controller(ctrl)
        btn.add_css_class("recording")
        self.toast("Press the key to use (Esc cancels)", 4)

        def key_pressed(_ctrl, keyval, _keycode, _state):
            name = _keyname(keyval)
            GLib.idle_add(self.remove_controller, ctrl)
            btn.remove_css_class("recording")
            if name != "Escape":
                row.set_text(name)
            return True

        ctrl.connect("key-pressed", key_pressed)

    # -- pages -------------------------------------------------------------------------

    def _build_general(self) -> None:
        page = Adw.PreferencesPage(name="general", icon_name="preferences-system-symbolic",
                                   title="General")
        grp = Adw.PreferencesGroup(title="General")
        lang = self._combo("general", "language", "Language",
                           [("auto (detect)", "auto")]
                           + [(c, c) for c in LANGUAGES],
                           subtitle="Whisper code the recognizer locks to")
        self.lang_row = lang
        grp.add(lang)
        grp.add(self._switch("general", "copy_to_clipboard",
                             "Copy transcriptions to clipboard",
                             "Every dictation also lands in the clipboard"))
        grp.add(self._switch("general", "tray_enabled", "Tray icon",
                             "Panel icon while the daemon runs "
                             "(toggle applies live)"))
        grp.add(self._switch("notifications", "enabled", "Notifications"))
        grp.add(self._switch("sounds", "enabled", "Sounds"))
        grp.add(self._spin("sounds", "volume", "Volume", 0.0, 1.0, 0.05,
                           digits=2))
        page.add(grp)
        page.add(self._save_group())
        self.add(page)

    def _build_models(self) -> None:
        page = Adw.PreferencesPage(name="models", icon_name="audio-x-generic-symbolic",
                                   title="Models")
        self.models_group = Adw.PreferencesGroup(
            title="Speech models",
            description="Local whisper models (faster-whisper)")
        page.add(self.models_group)

        warm = Adw.PreferencesGroup(title="State")
        self.warmup_row = Adw.ActionRow(title="Model", subtitle="—")
        self.warmup_spinner = Gtk.Spinner()
        self.warmup_row.add_suffix(self.warmup_spinner)
        warm.add(self.warmup_row)
        page.add(warm)

        engine = Adw.PreferencesGroup(title="Engine options",
                                      description="Changing these reloads the model")
        engine.add(self._combo(
            "model", "backend", "Backend",
            [("auto", "auto"), ("faster-whisper", "faster-whisper"),
             ("whisper-torch", "whisper-torch"), ("whisper.cpp", "whisper.cpp")]))
        engine.add(self._combo(
            "model", "device", "Device",
            [("auto", "auto"), ("cuda", "cuda"), ("cpu", "cpu")]))
        engine.add(self._combo(
            "model", "compute", "Compute",
            [("auto", "auto"), ("float16", "float16"), ("int8", "int8")]))
        engine.add(self._entry("model", "whispercpp_model",
                               "whisper.cpp model path (ggml/gguf)"))
        engine.add(self._switch("model", "eager_warmup", "Load at startup",
                                "Warm the model when the daemon starts "
                                "(needs a daemon restart)"))
        page.add(engine)
        page.add(self._save_group())
        self.add(page)

    def _refresh_models(self) -> None:
        for row in self._model_rows:
            self.models_group.remove(row)
        self._model_rows = []
        active = self._active_model()
        for name, info in model_catalog.MODEL_CATALOG.items():
            row = Adw.ActionRow(
                title=name,
                subtitle=(f"{info['size']} · {info['langs']} languages · "
                          f"{info['note']}"))
            if name == active:
                row.add_suffix(Gtk.Label(label="Active",
                                         css_classes=["success", "caption"]))
            else:
                downloaded = model_catalog.model_downloaded(name)
                btn = Gtk.Button(label="Use" if downloaded else "Download & use",
                                 css_classes=["suggested-action"])
                btn.set_valign(Gtk.Align.CENTER)
                btn.connect("clicked", self._pick_model, name)
                row.add_suffix(btn)
            self.models_group.add(row)
            self._model_rows.append(row)
        st = self.c.status() or {}
        warm = st.get("warmup") or {}
        if warm.get("running"):
            self.warmup_spinner.start()
            self.warmup_row.set_subtitle(f"loading {warm.get('model') or ''}…")
        elif warm.get("error"):
            self.warmup_row.set_subtitle(f"error: {warm['error']}")
        else:
            self.warmup_spinner.stop()
            self.warmup_row.set_subtitle(f"active: {active or '—'}")
        if st:  # about rows (daemon offline keeps the placeholder em-dash)
            self.about_backend_row.set_subtitle(st.get("backend") or "—")
            self.about_gpu_row.set_subtitle("yes" if st.get("cuda") else "no")

    def _active_model(self) -> str:
        name = str(self.cfg.get("model", {}).get("name", "auto"))
        if name in ("", "auto"):
            return backends.resolve_model_name(name)
        return backends.ALIASES.get(name.lower(), name.lower())

    def _pick_model(self, btn, name: str) -> None:
        try:
            resp = self.c.select_model(name)
        except Exception as e:
            self.toast(str(e))
            return
        if resp.get("ok") is False:
            self.toast(str(resp.get("error") or "failed"))
            return
        self.toast(f"Switching to {name}…")
        GLib.timeout_add_seconds(1, self._poll_model)

    def _poll_model(self) -> bool:
        self.cfg, self._from_daemon = self.c.get_config()
        self._refresh_models()
        warm = (self.c.status() or {}).get("warmup") or {}
        if warm.get("running"):
            return True
        if warm.get("error"):
            self.toast(f"model error: {warm['error']}")
        return False

    # -- AI page -------------------------------------------------------------------------

    def _build_ai(self) -> None:
        page = Adw.PreferencesPage(name="ai", icon_name="weather-few-clouds-symbolic",
                                   title="AI Polish")
        grp = Adw.PreferencesGroup(
            title="AI polish",
            description="Any OpenAI-compatible endpoint — Ollama, LM Studio, "
                        "OpenAI, Groq…")
        grp.add(self._switch("ai", "enabled", "Enabled"))
        grp.add(self._entry("ai", "base_url", "Base URL — http://localhost:11434/v1"))
        grp.add(self._entry("ai", "model", "Model — e.g. qwen3:8b"))
        grp.add(self._entry("ai", "api_key_env", "API key env var (preferred)"))
        grp.add(self._spin("ai", "temperature", "Temperature", 0.0, 2.0, 0.1,
                           digits=1))
        grp.add(self._spin("ai", "timeout_seconds", "Timeout (s)", 1, 3600, 5))
        grp.add(self._spin("ai", "max_retries", "Max retries", 0, 10, 1))
        test_row = Adw.ActionRow(title="Test connection")
        test_btn = Gtk.Button(label="Test", css_classes=["suggested-action"])
        test_btn.set_valign(Gtk.Align.CENTER)
        self.test_out = Gtk.Label(css_classes=["dim-label"], wrap=True,
                                  max_width_chars=28)
        test_btn.connect("clicked", self._test_ai)
        test_row.add_suffix(self.test_out)
        test_row.add_suffix(test_btn)
        grp.add(test_row)
        page.add(grp)

        self.rules_group = Adw.PreferencesGroup(
            title="Per-app prompts",
            description="Extra polish instructions when dictating into a "
                        "matching app (first match wins, * = everywhere)")
        add_row = Adw.ActionRow(title="Add rule")
        add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat"])
        add_btn.connect("clicked", lambda *_: self._add_rule({}))
        add_row.add_suffix(add_btn)
        self.rules_group.add(add_row)
        page.add(self.rules_group)

        cmd = Adw.PreferencesGroup(
            title="Command mode",
            description="Voice → terminal agent. Every command needs confirmation.")
        cmd.add(self._spin("command", "max_turns", "Max agent turns", 1, 20, 1))
        cmd.add(self._entry("command", "working_dir",
                            "Working directory (empty = home)"))
        cmd.add(self._spin("command", "timeout_seconds", "Command timeout (s)",
                           1, 3600, 5, digits=1))
        cmd.add(self._spin("command", "confirm_timeout_s",
                           "Confirmation timeout (s)", 5, 600, 5, digits=1))
        page.add(cmd)
        page.add(self._save_group())
        self.add(page)

    def _test_ai(self, _btn) -> None:
        self.test_out.set_text("testing…")
        url = self._get_text("ai", "base_url")
        model = self._get_text("ai", "model")

        def work():
            try:
                resp = self.c.test_ai(url, model)
            except Exception as e:  # surfaced inline
                resp = {"ok": False, "error": str(e)}
            GLib.idle_add(self.test_out.set_text,
                          f"ok: {resp['reply']}" if resp.get("ok")
                          else str(resp.get("error") or "failed"))
        threading.Thread(target=work, daemon=True).start()

    def _get_text(self, sec, key) -> str:
        row = self._rows.get((sec, key))
        return row.get_text() if isinstance(row, Adw.EntryRow) else ""

    # -- per-app prompt rules --------------------------------------------------------

    def _load_rules(self, rules: list) -> None:
        for r in list(self._rule_rows):
            self.rules_group.remove(r["expander"])
        self._rule_rows = []
        for rule in rules:
            self._add_rule(rule)

    def _add_rule(self, rule: dict) -> None:
        exp = Adw.ExpanderRow(title=", ".join(rule.get("apps", [])) or "New rule")
        apps = Adw.EntryRow(title="App patterns (comma-separated)")
        apps.set_text(", ".join(rule.get("apps", [])))

        tv = Gtk.TextView(hexpand=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        buf = tv.get_buffer()
        buf.set_text(str(rule.get("instructions", "")))

        remove_btn = Gtk.Button(icon_name="user-trash-symbolic",
                                css_classes=["flat", "destructive-action"])
        head = Adw.ActionRow(title="Instructions")
        head.add_suffix(remove_btn)
        exp.add_row(apps)
        exp.add_row(head)
        exp.add_row(_InstructionRow(tv))
        row_ref = {"expander": exp, "apps": apps, "buf": buf}
        remove_btn.connect("clicked", self._remove_rule, row_ref)

        def sync_title(*_):
            exp.set_title(apps.get_text().strip() or "New rule")
            self._touch()
        apps.connect("changed", sync_title)
        buf.connect("changed", lambda *_: self._touch())
        self._rule_rows.append(row_ref)
        self.rules_group.add(exp)
        exp.set_expanded(not rule.get("apps"))

    def _remove_rule(self, _btn, row_ref: dict) -> None:
        self.rules_group.remove(row_ref["expander"])
        self._rule_rows.remove(row_ref)
        self._touch()

    def _collect_rules(self):
        rules = []
        for r in self._rule_rows:
            apps = [a.strip() for a in r["apps"].get_text().split(",")
                    if a.strip()]
            text = r["buf"].get_text(r["buf"].get_start_iter(),
                                     r["buf"].get_end_iter(), False).strip()
            if apps and text:
                rules.append({"apps": apps, "instructions": text})
            elif apps or text:
                self.toast("Incomplete per-app rule skipped (needs apps "
                           "and instructions)")
        return rules

    # -- custom dictionary (upstream Custom Dictionary) ---------------------------

    def _load_dictionary(self, entries: list) -> None:
        for r in list(self._dict_rows):
            self.dict_group.remove(r["exp"])
        self._dict_rows = []
        for entry in entries:
            self._add_dict_word(entry)

    def _add_dict_word(self, entry: dict) -> None:
        exp = Adw.ExpanderRow(
            title=", ".join(entry.get("triggers", [])) or "New word")
        trig = Adw.EntryRow(title="Triggers (comma-separated)")
        trig.set_text(", ".join(entry.get("triggers", [])))
        repl = Adw.EntryRow(title="Replacement")
        repl.set_text(str(entry.get("replacement", "")))
        rm = Gtk.Button(icon_name="user-trash-symbolic",
                        css_classes=["flat", "destructive-action"],
                        tooltip_text="Remove this word")
        exp.add_suffix(rm)
        exp.add_row(trig)
        exp.add_row(repl)
        ref = {"exp": exp, "trig": trig, "repl": repl}
        rm.connect("clicked", self._remove_dict_word, ref)

        def sync_title(*_):
            exp.set_title(trig.get_text().strip() or "New word")
            self._touch()
        trig.connect("changed", sync_title)
        repl.connect("changed", lambda *_: self._touch())
        self._dict_rows.append(ref)
        self.dict_group.add(exp)
        exp.set_expanded(not entry.get("triggers"))

    def _remove_dict_word(self, _btn, ref: dict) -> None:
        self.dict_group.remove(ref["exp"])
        self._dict_rows.remove(ref)
        self._touch()

    def _collect_dictionary(self) -> list:
        entries = []
        for r in self._dict_rows:
            triggers = [t.strip() for t in r["trig"].get_text().split(",")
                        if t.strip()]
            replacement = r["repl"].get_text().strip()
            if triggers and replacement:
                entries.append({"triggers": triggers,
                                "replacement": replacement})
            elif triggers or replacement:
                self.toast("Incomplete dictionary word skipped (needs "
                           "triggers and a replacement)")
        return entries

    # -- dictation page -----------------------------------------------------------------

    def _build_dictation(self) -> None:
        page = Adw.PreferencesPage(name="dictation", 
            icon_name="preferences-desktop-keyboard-symbolic", title="Dictation")

        hk = Adw.PreferencesGroup(title="Hotkeys")
        hk.add(self._entry("hotkey", "key", "Dictation key — e.g. Right_Control, F9",
                           capture=True))
        hk.add(self._combo("hotkey", "mode", "Mode",
                           [("toggle", "toggle"), ("hold", "hold")],
                           subtitle="tap to start/stop · modifier-only keys "
                                    "need toggle"))
        hk.add(self._entry("hotkey", "cancel_key", "Cancel key — discards a take",
                           capture=True))
        hk.add(self._entry("hotkey", "rewrite_key", "Rewrite key (optional, needs AI)",
                           capture=True))
        hk.add(self._entry("hotkey", "command_key",
                           "Command key (optional, needs AI)", capture=True))
        mods = Adw.ActionRow(title="Extra modifiers",
                             subtitle="held in addition to the dictation key")
        for mod in ("ctrl", "alt", "shift", "super"):
            tb = Gtk.ToggleButton(label=mod, css_classes=["flat"])
            tb.set_valign(Gtk.Align.CENTER)
            tb.connect("toggled", lambda *_: self._touch())
            self._mod_toggles[mod] = tb
            mods.add_suffix(tb)
        hk.add(mods)
        page.add(hk)

        mic = Adw.PreferencesGroup(title="Microphone and recording")
        self.mic_row = Adw.ComboRow(title="Microphone",
                                    subtitle="Auto follows the system default")
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic",
                                 css_classes=["flat"], tooltip_text="Refresh list")
        refresh_btn.connect("clicked", lambda *_: self._fill_mics())
        self.mic_row.add_suffix(refresh_btn)
        self.mic_row.connect("notify::selected", lambda *_: self._touch())
        mic.add(self.mic_row)
        mic.add(self._combo("recording", "command", "Recorder",
                            [("auto", "auto"), ("pw-record", "pw-record"),
                             ("parecord", "parecord")]))
        mic.add(self._spin("recording", "max_seconds", "Max duration (s)",
                           5, 3600, 5))
        mic.add(self._spin("recording", "first_pcm_timeout", "No-audio timeout (s)",
                           0, 60, 0.5, digits=1,
                           subtitle="0 = off; stops a muted/wrong mic fast"))
        mic.add(self._switch("recording", "skip_silent", "Skip silent takes",
                             "Discard obviously-silent recordings ≤ 4 s"))
        mic.add(self._switch("recording", "pause_media", "Pause media",
                             "Pause MPRIS players while dictating"))
        page.add(mic)

        preview = Adw.PreferencesGroup(
            title="Live preview",
            description="The pill overlay with partial text while recording")
        preview.add(self._switch("recording", "preview_enabled", "Enabled"))
        preview.add(self._combo("recording", "preview_mode", "Mode",
                                [("auto", "auto"), ("overlay", "overlay"),
                                 ("notify", "notifications only")]))
        preview.add(self._combo("recording", "preview_overlay_size", "Size",
                                [("pill", "pill"), ("small", "small"),
                                 ("medium", "medium"), ("large", "large")],
                                subtitle="macOS size presets"))
        preview.add(self._spin("recording", "preview_bottom_offset",
                               "Bottom offset (px)", 0, 400, 2))
        preview.add(self._spin("recording", "preview_interval",
                               "Update interval (s)", 0.3, 10.0, 0.1, digits=1))
        preview.add(self._spin("recording", "preview_min_audio",
                               "First partial after (s)", 0.3, 10.0, 0.1,
                               digits=1))
        page.add(preview)

        polish = Adw.PreferencesGroup(title="Text polish")
        polish.add(self._switch("processing", "remove_filler_words",
                                "Remove filler words",
                                "um, uh, hmm… before punctuation"))
        fillers = Adw.EntryRow(title="Filler words (comma-separated)")
        fillers.connect("changed", lambda *_: self._touch())
        self._rows[("processing", "filler_words")] = _ListProxy(fillers)
        polish.add(fillers)
        polish.add(self._switch("processing", "punctuation_enabled",
                                "Spoken punctuation", '"literal comma" → ,'))
        polish.add(self._entry("processing", "punctuation_prefix",
                               "Spoken-command prefix"))
        gaav = Adw.ExpanderRow(
            title="Search-field formatting (GAAV)",
            subtitle="lowercase first letter, drop the final period")
        gaav.add_row(self._plain_switch_row("processing", "gaav_enabled",
                                            "Enabled"))
        gaav.add_row(self._plain_switch_row("processing", "gaav_lowercase_first",
                                            "Lowercase first letter"))
        gaav.add_row(self._plain_switch_row(
            "processing", "gaav_remove_trailing_period", "Remove trailing period"))
        polish.add(gaav)

        send = Adw.ExpanderRow(
            title="Spoken send",
            subtitle='a trailing phrase strips and presses Enter')
        send.add_row(self._plain_switch_row("recording", "spoken_send_enabled",
                                            "Enabled"))
        phrase = self._entry("recording", "spoken_send_phrase", "Phrase")
        send.add_row(phrase)
        send.add_row(self._combo("recording", "spoken_send_key", "Key",
                                 [("enter", "enter"),
                                  ("shift+enter", "shift+enter"),
                                  ("ctrl+enter", "ctrl+enter")]))
        polish.add(send)
        page.add(polish)

        self.dict_group = Adw.PreferencesGroup(
            title="Custom dictionary",
            description='Phrases replaced on insert — "miro board" → "Miro board"')
        add_w = Adw.ActionRow(title="Add word")
        add_w_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat"])
        add_w_btn.connect("clicked", lambda *_: self._add_dict_word({}))
        add_w.add_suffix(add_w_btn)
        self.dict_group.add(add_w)
        page.add(self.dict_group)

        ins = Adw.PreferencesGroup(title="Insertion",
                                   description="How typed text reaches your apps")
        ins.add(self._combo("insertion", "mode", "Mode",
                            [("auto", "auto"), ("typed", "typed"),
                             ("paste", "paste")]))
        ins.add(self._spin("insertion", "type_delay_ms", "Typing delay (ms)",
                           0, 1000, 1))
        ins.add(self._spin("insertion", "paste_threshold_chars",
                           "Paste threshold (chars)", 1, 100000, 50))
        page.add(ins)
        page.add(self._save_group())
        self.add(page)

    def _fill_mics(self) -> None:
        values: list[tuple[str, str]] = [("Auto (system default)", "")]
        for m in self.c.mics():
            label = m["description"] + ("  · default" if m.get("default") else "")
            values.append((label, m["name"]))
        current = str(self.cfg.get("recording", {}).get("device", "") or "")
        value_list = [v for _l, v in values]
        if current and current not in value_list:
            values.append((current + "  · saved", current))
            value_list.append(current)
        model = Gtk.StringList()
        for label, _v in values:
            model.append(label)
        self.mic_row.set_model(model)
        self._rows[("recording", "device")] = self.mic_row
        self._combo_values[("recording", "device")] = value_list
        self._loading = True
        self.mic_row.set_selected(value_list.index(current)
                                  if current in value_list else 0)
        self._loading = False

    # -- history page -----------------------------------------------------------------

    def _build_history_page(self) -> None:
        page = Adw.PreferencesPage(name="history", icon_name="document-open-recent-symbolic",
                                   title="History")
        grp = Adw.PreferencesGroup(title="History")
        grp.add(self._switch("history", "save", "Save transcriptions"))
        grp.add(self._switch("history", "save_audio", "Keep audio",
                             "Store the recording with each entry"))
        grp.add(self._spin("history", "audio_budget_gb", "Audio budget (GB)",
                           0.0, 1024.0, 0.5, digits=1))
        clear = Adw.ActionRow(title="Clear all history",
                              subtitle="Delete every entry and retained audio")
        clear_btn = Gtk.Button(label="Clear…", css_classes=["destructive-action"])
        clear_btn.set_valign(Gtk.Align.CENTER)
        clear_btn.connect("clicked", self._confirm_clear_history)
        clear.add_suffix(clear_btn)
        grp.add(clear)
        browse = Adw.ActionRow(title="Browse history",
                               subtitle="Open the History window")
        b_btn = Gtk.Button(icon_name="go-next-symbolic", css_classes=["flat"])
        b_btn.connect("clicked", lambda *_: (self.get_application()
                                             and self.get_application()
                                             .show_history()))
        browse.add_suffix(b_btn)
        grp.add(browse)
        page.add(grp)
        page.add(self._save_group())
        self.add(page)

    def _confirm_clear_history(self, _btn) -> None:
        def confirmed(dialog, response):
            if response == "clear":
                removed = self.c.history_clear()
                self.toast(f"Removed {removed} entries")
        dlg = Adw.MessageDialog(
            transient_for=self, modal=True, heading="Clear all history?",
            body="Every saved transcription and any retained audio will be "
                 "deleted. This cannot be undone.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("clear", "Clear All")
        dlg.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", confirmed)
        dlg.present()

    # -- about -----------------------------------------------------------------------

    def _build_about(self) -> None:
        page = Adw.PreferencesPage(name="about", icon_name="help-about-symbolic", title="About")
        grp = Adw.PreferencesGroup(title="About")
        from .. import paths
        grp.add(Adw.ActionRow(title="Version", subtitle=APP_VERSION))
        self.about_backend_row = Adw.ActionRow(title="Backend", subtitle="—")
        self.about_gpu_row = Adw.ActionRow(title="GPU (CUDA)", subtitle="—")
        grp.add(self.about_backend_row)
        grp.add(self.about_gpu_row)
        for title, value in (
                ("Config file", str(paths.config_file())),
                ("Control socket", str(paths.socket_path())),
                ("History", str(paths.data_dir() / "history.jsonl"))):
            grp.add(Adw.ActionRow(title=title, subtitle=value))
        about_btn_row = Adw.ActionRow(title="About FluidVoice Linux")
        about_btn = Gtk.Button(icon_name="help-about-symbolic",
                               css_classes=["flat"])
        about_btn.connect("clicked", self._show_about_dialog)
        about_btn_row.add_suffix(about_btn)
        grp.add(about_btn_row)
        page.add(grp)
        self.add(page)

    def _show_about_dialog(self, *_args) -> None:
        dlg = Adw.AboutDialog(
            application_name="FluidVoice Linux",
            application_icon="audio-input-microphone",
            version=APP_VERSION,
            website="https://github.com/acailic/FluidVoice-Linux",
            issue_url="https://github.com/acailic/FluidVoice-Linux/issues",
            license_type=Gtk.License.GPL_3_0)
        dlg.present(self)


def _default(section: str, key: str):
    return DEFAULTS.get(section, {}).get(key)


def _keyname(keyval) -> str:
    name = Gdk.keyval_name(keyval) or ""
    if len(name) == 1 and name.isalpha():
        return name.lower()
    return _KEY_REMAP.get(name, name)
