"""Session lock/suspend watch for the daemon's pause_when_locked feature.

Sources, in priority order (all additive; the first flip wins and later
same-value signals are deduped):

1. logind session Lock()/Unlock() signals on the session object
   (`loginctl lock-session` path).
2. org.freedesktop.DBus.Properties.PropertiesChanged carrying LockedHint
   on the same session object - GNOME's path: it sets the property, and
   on this GNOME no screensaver D-Bus name is ever owned (verified live;
   relying on ActiveChanged alone would miss every GNOME lock).
3. Manager PrepareForSleep(bool) on /org/freedesktop/login1 - suspend
   counts as locked (a suspended screen with a live dictation is exactly
   the bug this feature fixes).
4. org.freedesktop.ScreenSaver / org.gnome.ScreenSaver ActiveChanged(bool)
   on the session bus, where a DE owns the names (KDE/XFCE paths).

A 5 s LockedHint property poll inside the GLib loop reconciles any missed
signal. Without D-Bus, logind, or a resolvable session, start() returns
False and the feature is off (headless/test boxes). The monitor fires
on_change(locked) ONLY on transitions (see _apply) - callers can treat
every callback as an edge.

Session path resolution (probe-verified): $XDG_SESSION_ID ->
/org/freedesktop/login1/session/<id> first; else Manager.GetSessionByPID
(os.getpid()) which works only for processes inside the session
(autostart/systemd-user daemons; agent shells get NoSessionForPID).
/proc/self/sessionid is the KERNEL session id, not logind's - never use it.
"""
from __future__ import annotations

import os
import threading
from typing import Callable

LOGIN1 = "org.freedesktop.login1"
MANAGER_PATH = "/org/freedesktop/login1"
MANAGER_IFACE = "org.freedesktop.login1.Manager"
SESSION_IFACE = "org.freedesktop.login1.Session"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

# screensaver names a DE may own on the session bus (fallback sources)
SCREENSAVER_NAMES = ("org.freedesktop.ScreenSaver", "org.gnome.ScreenSaver")

RECONCILE_INTERVAL_S = 5.0


def session_path_from_env() -> str | None:
    """/org/freedesktop/login1/session/<id> from $XDG_SESSION_ID, or None."""
    sid = (os.environ.get("XDG_SESSION_ID") or "").strip()
    if not sid or "/" in sid:  # defensive: it is a plain id, never a path
        return None
    return f"{MANAGER_PATH}/session/{sid}"


class LockMonitor:
    """Flips on_change(locked: bool) on lock/unlock/suspend transitions.

    Transitions only: the monitor dedups, so two lock signals in a row
    fire one callback. Every handler is a plain method (directly
    unit-testable without a bus); start() wires them to real signals."""

    def __init__(self, on_change: Callable[[bool], None],
                 log: Callable[[str], None] = (lambda m: None)):
        self._on_change = on_change
        self._log = log
        self._locked = False
        self._applied = False  # any _apply ran (initial state counts)
        self._loop = None
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._started: bool | None = None  # tri-state: thread reports
        self._bus = None
        self._session_obj = None
        self.session_path: str | None = None

    # -- state machine --------------------------------------------------------

    @property
    def locked(self) -> bool:
        return self._locked

    def _apply(self, locked: bool, source: str) -> bool:
        """Apply one observation; fire on_change only on a flip. Returns
        True when the state actually changed (initial observation from
        False counts as a change only if it is a lock - an unlocked start
        is the assumed baseline and stays silent)."""
        locked = bool(locked)
        changed = self._locked != locked
        self._locked = locked
        self._applied = True
        if changed:
            try:
                self._on_change(locked)
            except Exception as e:  # noqa: BLE001 - must not kill the bus loop
                self._log(f"lock state callback failed "
                          f"({e.__class__.__name__}: {e})")
        return changed

    # -- signal handlers (plain methods: directly testable) -------------------

    def _on_session_lock(self) -> None:
        self._apply(True, "logind Lock")

    def _on_session_unlock(self) -> None:
        self._apply(False, "logind Unlock")

    def _on_session_props_changed(self, iface, props, _signature) -> None:
        # GNOME's path: the session sets LockedHint instead of emitting Lock
        if "LockedHint" in (props or {}):
            self._apply(bool(props["LockedHint"]), "LockedHint")

    def _on_prepare_for_sleep(self, sleeping) -> None:
        self._apply(bool(sleeping), "PrepareForSleep")

    def _on_screensaver_active(self, active) -> None:
        self._apply(bool(active), "screensaver ActiveChanged")

    # -- session resolution -----------------------------------------------------

    def _session_path(self, bus=None, manager=None) -> str | None:
        """Logind session object path for THIS process: $XDG_SESSION_ID
        first, else Manager.GetSessionByPID(os.getpid()). None when the
        bus/logind/session is unavailable (headless, agent shells).
        `manager` is a test seam standing in for the GetSessionByPID
        proxy."""
        try:
            path = session_path_from_env()
            if path is not None:
                return path
            if manager is None:
                bus = bus or self._bus
                if bus is None:
                    return None
                import dbus
                manager = dbus.Interface(
                    bus.get_object(LOGIN1, MANAGER_PATH), MANAGER_IFACE)
            result = manager.GetSessionByPID(os.getpid(), timeout=5)
            return str(result) if result else None
        except Exception as e:  # noqa: BLE001 - best-effort contract
            self._log(f"lock watch: session lookup failed "
                      f"({e.__class__.__name__}: {e})")
            return None

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> bool:
        """Run the whole setup on the monitor thread and report success:
        resolve the session, subscribe to every source, run the GLib loop.
        Returns False (logged) when dbus/GLib is missing, logind is absent,
        or no session resolves.

        NB: the bus connection is created on the thread AFTER
        DBusGMainLoop(set_as_default=True) - dbus-python caches
        connections per process, and a SystemBus created without a main
        loop attached can never receive signals (live-verified: the
        subscriptions raise "D-Bus connections must be attached to a main
        loop"). The tray owns the SESSION bus; the SYSTEM bus is ours."""
        try:
            import dbus  # noqa: F401
            from dbus.mainloop.glib import DBusGMainLoop  # noqa: F401
            from gi.repository import GLib  # noqa: F401
        except Exception as e:
            self._log(f"lock watch unavailable ({e.__class__.__name__}: {e})")
            return False
        self._started: bool | None = None  # tri-state until the thread says
        ready = threading.Event()
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, args=(ready,),
                                        name="fluidvoice-lockmon", daemon=True)
        self._thread.start()
        ready.wait(timeout=8)
        return bool(self._started)

    def _run(self, ready: threading.Event) -> None:
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
        loop = None
        try:
            DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()
            self._bus = bus
            path = self._session_path(bus)
            if path is None:
                self._log("lock watch unavailable (no logind session for "
                          "this process - headless?)")
                self._started = False
                return
            self.session_path = path
            session = bus.get_object(LOGIN1, path)
            self._session_obj = session
            session.connect_to_signal("Lock", self._on_session_lock,
                                      dbus_interface=SESSION_IFACE)
            session.connect_to_signal("Unlock", self._on_session_unlock,
                                      dbus_interface=SESSION_IFACE)
            bus.add_signal_receiver(
                self._on_session_props_changed,
                signal_name="PropertiesChanged",
                dbus_interface=PROPS_IFACE, path=path)
            manager = bus.get_object(LOGIN1, MANAGER_PATH)
            manager.connect_to_signal("PrepareForSleep",
                                      self._on_prepare_for_sleep,
                                      dbus_interface=MANAGER_IFACE)
            # screensaver fallback: additive, only where a DE owns the names
            try:
                sbus = dbus.SessionBus()
                for name in SCREENSAVER_NAMES:
                    sbus.add_signal_receiver(
                        self._on_screensaver_active,
                        signal_name="ActiveChanged",
                        dbus_interface=name)
            except Exception:
                pass  # optional source
            # initial truth + the reconcile poll inside the loop
            self._reconcile()
            loop = GLib.MainLoop()
            self._loop = loop
            GLib.timeout_add_seconds(int(RECONCILE_INTERVAL_S),
                                     self._reconcile_loop)
            self._started = True
        except Exception as e:  # noqa: BLE001 - best-effort contract
            self._log(f"lock watch failed ({e.__class__.__name__}: {e})")
            self._started = False
        finally:
            ready.set()
        if loop is not None and not self._stop_flag.is_set():
            loop.run()

    def _reconcile(self) -> bool:
        """Read the session's LockedHint property; deduped through _apply.
        Returns True for the GLib timeout (keep polling)."""
        if self._session_obj is None:
            return True
        try:
            import dbus
            props = dbus.Interface(self._session_obj, PROPS_IFACE)
            hint = bool(props.Get(SESSION_IFACE, "LockedHint", timeout=5))
            self._apply(hint, "reconcile")
        except Exception:
            pass  # bus hiccup: the next poll retries
        return True  # GLib: keep the timeout alive

    def _reconcile_loop(self) -> bool:
        if self._stop_flag.is_set():
            return False  # GLib: drop the timeout
        return self._reconcile()

    def stop(self) -> None:
        """Best-effort, idempotent."""
        self._stop_flag.set()
        loop, self._loop = self._loop, None
        if loop is not None:
            try:
                loop.quit()
            except Exception:
                pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)
