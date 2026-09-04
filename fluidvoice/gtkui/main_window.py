"""History window — the main window (macOS app's transcript list counterpart).

Live status header, search, entry cards with copy / delete / inline audio
replay, clear-all. Reads history directly from the JSONL (no daemon needed);
status/toggle need the daemon and degrade to a banner when it is down.
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timedelta

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import history as history_mod
from ..history import format_today
from .client import Client


class AudioReplayer(Gtk.Box):
    """Compact play/pause + position for one retained WAV (Gtk.MediaFile,
    with an open-externally fallback when GStreamer can't handle it)."""

    def __init__(self, path):
        super().__init__(spacing=8)
        self.path = path
        self.media = None
        self._tick = 0
        self.play_btn = Gtk.ToggleButton(icon_name="media-playback-start-symbolic")
        self.play_btn.connect("toggled", self._on_toggle)
        self.pos = Gtk.Label(label="0:00", css_classes=["dim-label"])
        self.append(self.play_btn)
        self.append(self.pos)
        try:
            media = Gtk.MediaFile.for_filename(str(path))
            media.connect("notify::playing", self._sync)
            media.connect("notify::timestamp", lambda *_: self._update_pos())
            media.connect("notify::error", lambda *_: self._fallback())
            self.media = media
        except Exception:
            self._fallback()

    def _fallback(self) -> None:
        """GStreamer missing/broken: offer opening the file instead."""
        if self.media is None and self.get_first_child() is not self.play_btn:
            return  # already fallen back
        self.media = None
        self.play_btn.set_visible(False)
        self.pos.set_visible(False)
        btn = Gtk.Button(label="Open audio", icon_name="folder-open-symbolic",
                         css_classes=["flat"])
        btn.connect("clicked", lambda *_: subprocess.Popen(
            ["xdg-open", str(self.path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        self.append(btn)

    def _on_toggle(self, btn) -> None:
        if self.media is None:
            return
        if btn.get_active():
            self.media.play()
            if not self._tick:
                self._tick = GLib.timeout_add(300, self._update_pos)
        else:
            self.media.pause()

    def _sync(self, *_) -> None:
        playing = bool(self.media and self.media.get_playing())
        if self.play_btn.get_active() != playing:
            self.play_btn.set_active(playing)
        self.play_btn.set_icon_name(
            "media-playback-pause-symbolic" if playing
            else "media-playback-start-symbolic")
        if not playing and self._tick:
            GLib.source_remove(self._tick)
            self._tick = 0

    def _update_pos(self) -> bool:
        if self.media is None:
            return False
        pos = self.media.get_timestamp() / 1e9
        dur = self.media.get_duration() / 1e9
        if dur > 0:
            self.pos.set_text(f"{int(pos // 60)}:{int(pos % 60):02d} / "
                              f"{int(dur // 60)}:{int(dur % 60):02d}")
        return True


class HistoryEntryRow(Gtk.ListBoxRow):
    """One dictation: meta line, text, actions, optional audio replay,
    plus inline repair (edit + re-insert, research §4: correction must be
    one step away) and honest confidence dots (research §5)."""

    CONFIDENCE_DOTS = {2: "●●●", 1: "●●○", 0: "●○○"}
    CONFIDENCE_WORD = {2: "high", 1: "mixed", 0: "low"}

    def __init__(self, entry, on_delete, on_copy, on_insert=None,
                 on_edit=None):
        super().__init__(activatable=False, selectable=False,
                         css_classes=["card"])
        self.entry = entry
        self.editor: Gtk.Box | None = None
        self.on_edit = on_edit
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=10, margin_bottom=10,
                      margin_start=14, margin_end=10)
        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ts = entry.get("ts") or 0
        meta.append(Gtk.Label(
            label=datetime.fromtimestamp(ts).strftime("%a %d %b, %H:%M"),
            css_classes=["dim-label"]))
        if entry.get("duration_s"):
            meta.append(Gtk.Label(
                label=f"{float(entry['duration_s']):.1f} s",
                css_classes=["dim-label"]))
        if entry.get("app"):
            meta.append(Gtk.Label(label=str(entry["app"]),
                                  css_classes=["caption", "dim-label"]))
        if entry.get("mode") and entry.get("mode") != "dictate":
            meta.append(Gtk.Label(label=str(entry["mode"]),
                                  css_classes=["caption", "dim-label"]))
        if entry.get("ai"):
            meta.append(Gtk.Label(label="AI polished",
                                  css_classes=["caption", "accent"]))
        conf = entry.get("confidence")
        if conf in self.CONFIDENCE_DOTS:
            meta.append(Gtk.Label(
                label=self.CONFIDENCE_DOTS[conf],
                tooltip_text=f"Recognition confidence: "
                             f"{self.CONFIDENCE_WORD[conf]}",
                css_classes=["dim-label"]))
        meta.append(Gtk.Box(hexpand=True))  # spacer
        if on_insert is not None:
            ins_btn = Gtk.Button(icon_name="edit-paste-symbolic",
                                 css_classes=["flat"],
                                 tooltip_text="Insert at cursor")
            ins_btn.connect("clicked", on_insert, self)
            meta.append(ins_btn)
        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic",
                              css_classes=["flat"],
                              tooltip_text="Copy text")
        copy_btn.connect("clicked", on_copy, self)
        meta.append(copy_btn)
        edit_btn = Gtk.Button(icon_name="document-edit-symbolic",
                              css_classes=["flat"],
                              tooltip_text="Edit text")
        edit_btn.connect("clicked", self._start_edit)
        meta.append(edit_btn)
        del_btn = Gtk.Button(icon_name="user-trash-symbolic",
                             css_classes=["flat", "destructive-action"],
                             tooltip_text="Delete entry")
        del_btn.connect("clicked", on_delete, self)
        meta.append(del_btn)
        box.append(meta)

        self.text_lbl = Gtk.Label(
            label=str(entry.get("text") or entry.get("raw") or ""),
            wrap=True, xalign=0.0, hexpand=True, css_classes=["body"])
        box.append(self.text_lbl)

        if entry.get("audio"):
            path = entry.get("_audio_path")
            if path:
                box.append(AudioReplayer(path))
        self.set_child(box)

    # -- inline repair ---------------------------------------------------------

    def _start_edit(self, _btn) -> None:
        if self.editor is not None:
            return
        parent = self.get_child()
        self.text_lbl.set_visible(False)
        self.editor = self._build_editor()
        parent.append(self.editor)
        parent.reorder_child_after(self.editor, self.text_lbl)

    def _build_editor(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.set_size_request(-1, 72)
        view.get_buffer().set_text(
            str(self.entry.get("text") or self.entry.get("raw") or ""))
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                       halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel", css_classes=["flat"])
        save = Gtk.Button(label="Save", css_classes=["suggested-action"])
        btns.append(cancel)
        btns.append(save)
        box.append(view)
        box.append(btns)
        cancel.connect("clicked", lambda *_: self._end_edit(False, view))
        save.connect("clicked", lambda *_: self._end_edit(True, view))
        return box

    def _end_edit(self, apply: bool, view: Gtk.TextView) -> None:
        if apply and self.on_edit is not None:
            buf = view.get_buffer()
            new = buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                               False).strip()
            if new and new != str(self.entry.get("text") or ""):
                self.on_edit(self, new)  # persists + updates entry on success
        if self.editor is not None:
            self.get_child().remove(self.editor)
            self.editor = None
        self.text_lbl.set_text(
            str(self.entry.get("text") or self.entry.get("raw") or ""))
        self.text_lbl.set_visible(True)


def date_header_label(ts: float, now: datetime | None = None) -> str:
    """"Today" / "Yesterday" / "%a %d %b" bucket label for a timestamp."""
    day = datetime.fromtimestamp(ts).date()
    now = now or datetime.now()
    if day == now.date():
        return "Today"
    if day == (now - timedelta(days=1)).date():
        return "Yesterday"
    return day.strftime("%a %d %b")


class HistoryWindow(Adw.ApplicationWindow):
    def __init__(self, application=None, client=None):
        super().__init__(application=application, title="SayItErmano",
                         default_width=760, default_height=640)
        self.c = client or Client()
        self._entries: list[dict] = []
        self._query = ""
        self._search_debounce = 0

        # -- header ---------------------------------------------------------
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(title="SayItErmano", subtitle="idle")
        header.set_title_widget(self.title_widget)

        self.mic_btn = Gtk.Button(icon_name="audio-input-microphone-symbolic",
                                  css_classes=["suggested-action"],
                                  tooltip_text="Toggle dictation")
        self.mic_btn.connect("clicked", self._on_toggle)
        header.pack_start(self.mic_btn)

        menu = Gio.Menu()
        menu.append("Export…", "win.hist.export")
        menu.append("Clear All…", "win.hist.clear")
        self.menu_model = menu
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic",
                                       menu_model=menu, tooltip_text="Menu"))
        settings_btn = Gtk.Button(icon_name="preferences-system-symbolic",
                                  tooltip_text="Settings")
        settings_btn.connect("clicked", self._open_settings)
        header.pack_end(settings_btn)

        # -- layout ---------------------------------------------------------
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay = Adw.ToastOverlay(child=vbox)
        self.set_content(self.toast_overlay)
        vbox.append(header)

        self.down_banner = Adw.Banner(
            title="Daemon not running — history works, dictation does not",
            button_label="Retry", revealed=False)
        self.down_banner.connect("button-clicked", lambda *_: self.refresh())
        vbox.append(self.down_banner)

        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                         margin_top=8, margin_bottom=4,
                         margin_start=14, margin_end=14)
        self.state_dot = Gtk.Image(icon_name="object-select-symbolic",
                                   css_classes=["success"])
        self.state_lbl = Gtk.Label(label="idle", css_classes=["heading"])
        self.backend_lbl = Gtk.Label(css_classes=["dim-label"])
        self.gpu_lbl = Gtk.Label(css_classes=["dim-label"])
        self.model_lbl = Gtk.Label(css_classes=["dim-label"])
        self.warmup_spinner = Gtk.Spinner()
        self.warmup_lbl = Gtk.Label(css_classes=["dim-label"])
        self.today_lbl = Gtk.Label(css_classes=["dim-label"])
        for w in (self.state_dot, self.state_lbl, self.backend_lbl,
                  self.gpu_lbl, self.model_lbl, self.warmup_spinner,
                  self.warmup_lbl, self.today_lbl):
            status.append(w)
        vbox.append(status)

        self.search = Gtk.SearchEntry(placeholder_text="Search transcripts, apps…",
                                      margin_start=14, margin_end=14,
                                      margin_bottom=8)
        self.search.connect("changed", self._on_search_changed)
        vbox.append(self.search)

        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        vbox.append(scroll)
        self.listbox = Gtk.ListBox(css_classes=["boxed-list-separate"])
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_placeholder(Adw.StatusPage(
            title="No dictations yet",
            description="Press your hotkey and speak — transcripts land here.",
            icon_name="sayit-ermano",
            vexpand=True))
        scroll.set_child(self.listbox)

        self.count_lbl = Gtk.Label(css_classes=["dim-label"],
                                   margin_top=6, margin_bottom=10)
        vbox.append(self.count_lbl)

        self.install_action("hist.clear", None, self._on_clear_all)
        self.install_action("hist.export", None, self._on_export)
        self._exporting = False
        self._export_dlg = None
        self._load_history()
        self.refresh()
        GLib.timeout_add_seconds(2, self._poll)

    # -- data -----------------------------------------------------------------

    def _on_search_changed(self, entry) -> None:
        self._query = entry.get_text().strip()
        if self._search_debounce:
            GLib.source_remove(self._search_debounce)
        self._search_debounce = GLib.timeout_add(250, self._debounced_load)

    def _debounced_load(self) -> bool:
        self._search_debounce = 0
        self._load_history()
        return False

    def _load_history(self) -> None:
        try:
            self._entries = self.c.history(q=self._query, limit=200)
        except Exception:
            self._entries = []
        self._render()

    def _render(self) -> None:
        row = self.listbox.get_first_child()
        while row is not None:
            nxt = row.get_next_sibling()
            self.listbox.remove(row)
            row = nxt
        last_day = None
        for e in self._entries:
            ts = e.get("ts") or 0
            day = datetime.fromtimestamp(ts).date()
            if day != last_day:  # date headers: one glance = recency bucket
                last_day = day
                self.listbox.append(self._header_row(date_header_label(ts)))
            if e.get("audio"):
                e["_audio_path"] = history_mod.audio_path_for(e.get("ts", 0))
            self.listbox.append(
                HistoryEntryRow(e, self._on_delete_row, self._on_copy_row,
                                self._on_insert_row, self._on_edit_row))
        n = len(self._entries)
        self.count_lbl.set_text(
            f"{n} ent{'ry' if n == 1 else 'ries'}"
            + (" (showing latest 200)" if n >= 200 else ""))
        self._update_today()

    @staticmethod
    def _header_row(label: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        row.set_child(Gtk.Label(label=label, xalign=0.0,
                                css_classes=["heading", "dim-label"],
                                margin_top=10, margin_bottom=2,
                                margin_start=6))
        return row

    def _update_today(self) -> None:
        try:
            st = self.c.today_stats()
        except Exception:
            return
        self.today_lbl.set_text("today: " + format_today(st))

    # -- actions ----------------------------------------------------------------

    def _on_copy_row(self, _btn, row) -> None:
        text = str(row.entry.get("text") or row.entry.get("raw") or "")
        try:
            Gdk.Display.get_default().get_clipboard().set_text(text)
        except (AttributeError, TypeError):
            cb = Gdk.Display.get_default().get_clipboard()
            cb.set(Gdk.ContentProvider.new_for_bytes(
                "text/plain;charset=utf-8", GLib.Bytes.new(text.encode())))
        self._toast("Copied")

    def _on_insert_row(self, _btn, row) -> None:
        text = str(row.entry.get("text") or "")
        if not text:
            return
        try:
            self.c.insert_text(text)
            self._toast("Inserted at cursor")
        except Exception as e:  # noqa: BLE001 - daemon down/busy -> toast
            self._toast(f"Insert failed: {e}")

    def _on_edit_row(self, row, new_text: str) -> None:
        try:
            saved = self.c.history_update_text(row.entry.get("ts", 0),
                                               new_text)
        except Exception:  # noqa: BLE001 - unreadable history -> toast
            saved = False
        if saved:
            row.entry["text"] = new_text
            self._toast("Saved")
        else:
            self._toast("Save failed")

    def _on_delete_row(self, _btn, row) -> None:
        def confirmed(dialog, response):
            if response == "delete":
                self.c.history_delete(row.entry.get("ts", 0))
                self._load_history()
        dlg = Adw.MessageDialog(
            transient_for=self, modal=True, heading="Delete this entry?",
            body="The transcription"
                 + (" and its audio" if row.entry.get("audio") else "")
                 + " will be removed.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", confirmed)
        dlg.present()

    def _on_clear_all(self, *_args) -> None:
        def confirmed(dialog, response):
            if response == "clear":
                removed = self.c.history_clear()
                self._load_history()
                self._toast(f"Removed {removed} entries")
        dlg = Adw.MessageDialog(
            transient_for=self, modal=True, heading="Clear all history?",
            body="Every saved transcription and any retained audio will be "
                 "deleted. This cannot be undone.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("clear", "Clear All")
        dlg.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", confirmed)
        dlg.present()

    def _on_toggle(self, _btn) -> None:
        try:
            self.c.toggle()
        except Exception as e:
            self._toast(str(e))
        GLib.timeout_add(150, self.refresh)

    # -- export ------------------------------------------------------------------

    def _on_export(self, *_args) -> None:
        dlg = Gtk.FileChooserNative.new(
            "Export history", self, Gtk.FileChooserAction.SAVE,
            "_Export", "_Cancel")
        dlg.set_current_name(
            f"sayitermano-history-{time.strftime('%Y%m%d-%H%M%S')}.zip")
        dlg.connect("response", self._on_export_response)
        self._export_dlg = dlg  # keep alive while it runs its own loop
        dlg.show()

    def _on_export_response(self, dlg, response) -> None:
        self._export_dlg = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        f = dlg.get_file()
        path = f.get_path() if f is not None else None
        if path:
            self._export_to(path)

    def _export_to(self, path: str) -> None:
        """Enter the busy state, let one frame paint, then write the zip
        from an idle callback (everything stays on the main thread)."""
        self._exporting = True
        self.action_set_enabled("hist.export", False)
        self._toast("Exporting…")
        GLib.idle_add(self._export_now, path)

    def _export_now(self, path: str) -> bool:
        try:
            n, notes = self.c.export_zip(path)
            msg = f"Exported {n} entries"
            if notes:
                msg += f", {len(notes)} audio files skipped"
            self._toast(msg)
        except Exception as e:  # noqa: BLE001 - surfaced as a toast
            self._toast(f"export failed: {e}")
        finally:
            self._exporting = False
            self.action_set_enabled("hist.export", True)
        return False  # GLib.SOURCE_REMOVE - stop the idle source

    def _open_settings(self, _btn) -> None:
        app = self.get_application()
        if app is not None:
            app.show_settings()

    def _toast(self, text: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=text))

    # -- status polling ---------------------------------------------------------

    def refresh(self) -> bool:
        self._apply_status(self.c.status())
        self._update_today()  # a fresh dictation may have just landed
        return False

    def _poll(self) -> bool:
        GLib.idle_add(self._apply_status, self.c.status())
        return True  # keep polling

    def _apply_status(self, st: dict | None) -> None:
        if st is None:
            self.down_banner.set_revealed(True)
            self.mic_btn.set_sensitive(False)
            self.state_lbl.set_text("daemon offline")
            self.state_dot.set_from_icon_name("dialog-warning-symbolic")
            self.state_dot.set_css_classes(["warning"])
            return
        self.down_banner.set_revealed(False)
        self.mic_btn.set_sensitive(True)
        recording = bool(st.get("recording"))
        busy = bool(st.get("busy"))
        if recording:
            self.state_lbl.set_text("recording")
            self.state_dot.set_css_classes(["error"])
            self.state_dot.set_from_icon_name("media-record-symbolic")
            self.mic_btn.add_css_class("destructive-action")
            self.mic_btn.remove_css_class("suggested-action")
        else:
            self.state_lbl.set_text("processing…" if busy else "idle")
            self.state_dot.set_css_classes(["warning"] if busy else ["success"])
            self.state_dot.set_from_icon_name(
                "emblem-synchronizing-symbolic" if busy else "object-select-symbolic")
            self.mic_btn.add_css_class("suggested-action")
            self.mic_btn.remove_css_class("destructive-action")
        self.backend_lbl.set_text(f"backend {st.get('backend') or '—'}")
        self.gpu_lbl.set_text("GPU yes" if st.get("cuda") else "GPU no")
        model = st.get("active_model") or self._active_model_from_config()
        self.model_lbl.set_text(f"model {model or '—'}")
        warm = st.get("warmup") or {}
        if warm.get("running"):
            self.warmup_spinner.start()
            self.warmup_lbl.set_text(f"loading {warm.get('model') or ''}…")
        else:
            self.warmup_spinner.stop()
            self.warmup_lbl.set_text(
                f"model error: {warm['error']}" if warm.get("error") else "")
        self.title_widget.set_subtitle(self.state_lbl.get_text())

    @staticmethod
    def _active_model_from_config() -> str:
        from .. import backends
        from ..config import load_config
        name = str(load_config().get("model", {}).get("name", "auto"))
        if name in ("", "auto"):
            return backends.resolve_model_name(name)
        return backends.ALIASES.get(name.lower(), name.lower())
