#!/usr/bin/env python3
"""Media widget for the QNX Photon shelf: MPRIS transport and sink volume.

A component of bin/shelf-panel, and a window of its own when run directly so
it can be looked at without the panel around it.  It owns no geometry beyond
a size hint and it never talks to fvwm, which is what lets the panel host it
unchanged.

Why this is a program and not an FvwmScript any more is in PANEL-DESIGN.md.
The short of it: FvwmScript clears before it draws with no double buffering,
so every repaint flashes; its Icon property is broken on fvwm3 1.1.2, so the
transport had to be ASCII; and it has no way to scroll a title.  All three are
properties of the module, not of how we used it.

Nothing here polls. Track and playback state arrive as D-Bus
PropertiesChanged signals, the sink volume arrives on `pactl subscribe`,
and cover art is fetched when a new track names one -- a request that ends
with its image or its timeout, never with the next tick. The timers in the
file: the marquee (which stops when the title fits) and one abort guard per
in-flight art fetch. That is what removes the once-a-second white flash:
there is no once-a-second anything left. The one exception is the browser's
picture-in-picture window: nothing in X announces when one appears, so the
monitor polls the managed-window list; every other path here is event-
driven.

Run it standalone to look at it -- it is an ordinary window until something
swallows it.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#  qt6ct prints a line per palette lookup at startup and would have us adopt
#  a session theme we then paint over anyway.  Both are noise in a panel.
os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtCore import (QObject, QProcess, QRect, QSignalBlocker, QSize, Qt,
                          QTimer, QUrl, pyqtSignal, pyqtSlot)
from PyQt6.QtGui import (QFontMetrics, QImageReader, QPainter, QPalette,
                         QPolygon, QPixmap)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtCore import QBuffer, QIODevice, QPoint
from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PyQt6.QtWidgets import QApplication, QComboBox, QWidget

import photon
from Xlib import X, display, error as xerror

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

#  What separates the end of a scrolling title from its own beginning.  The
#  reference screenshot caught the CD Player mid-wrap ("er ... CD Playe"), so
#  this is a continuous wrap-around, not a ping-pong.
MARQUEE_SEP = "   ...   "
MARQUEE_MS = 60


#  ---- MPRIS ----------------------------------------------------------------

class Mpris(QObject):
    """One player's worth of state, kept current by signals.

    Which player is "the" player is decided on every rescan: a playing one
    wins, otherwise the first the bus lists.  Rescans happen on
    NameOwnerChanged, so a player that starts or quits is picked up without
    anyone asking the bus on a timer.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = None
        #  The unique bus name (":1.42") behind self.service.  Signals arrive
        #  stamped with that, never with the well-known org.mpris name, so
        #  without it every PropertiesChanged looks like it came from some
        #  other player.
        self.owner = None
        self.title = ""
        #  mpris:artUrl: the track's cover, published as a fetchable
        #  file:// or http(s) URI, or absent.  mpris:trackid tags the track
        #  so a slow art reply knows when it has gone stale.
        self.art_url = ""
        self.trackid = ""
        self.status = "Stopped"
        self.can_next = False
        self.can_prev = False
        self.can_control = False

        self.bus = QDBusConnection.sessionBus()
        #  An empty sender matches any, which is what we want: one match rule
        #  covers every player on the bus, present and future.
        self.bus.connect("", MPRIS_PATH, PROPS_IFACE, "PropertiesChanged",
                         self._on_props)
        self.bus.connect("org.freedesktop.DBus", "/org/freedesktop/DBus",
                         "org.freedesktop.DBus", "NameOwnerChanged",
                         self._on_name_owner)
        self.rescan()

    #  -- discovery --

    def _names(self):
        dbus = QDBusInterface("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", self.bus)
        reply = dbus.call("ListNames")
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            return []
        args = reply.arguments()
        if not args:
            return []
        return [n for n in args[0] if n.startswith(MPRIS_PREFIX)]

    def rescan(self):
        candidates = self._names()
        chosen = None
        for name in candidates:
            if self._get(name, "PlaybackStatus") == "Playing":
                chosen = name
                break
        if chosen is None and candidates:
            chosen = candidates[0]
        self.service = chosen
        self.owner = self._owner_of(chosen) if chosen else None
        self.refresh()

    def _owner_of(self, service):
        dbus = QDBusInterface("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", self.bus)
        reply = dbus.call("GetNameOwner", service)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            return None
        args = reply.arguments()
        return args[0] if args else None

    #  -- reading --

    def _props(self, service):
        return QDBusInterface(service, MPRIS_PATH, PROPS_IFACE, self.bus)

    def _get(self, service, name):
        reply = self._props(service).call("Get", PLAYER_IFACE, name)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            return None
        args = reply.arguments()
        return args[0] if args else None

    def refresh(self):
        if not self.service:
            self._clear()
            return
        reply = self._props(self.service).call("GetAll", PLAYER_IFACE)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            self._clear()
            return
        args = reply.arguments()
        self._apply(args[0] if args and isinstance(args[0], dict) else {})

    def _clear(self):
        self.owner = None
        self.title = ""
        self.art_url = ""
        self.trackid = ""
        self.status = "Stopped"
        self.can_next = self.can_prev = self.can_control = False
        self.changed.emit()

    def _apply(self, props):
        if "Metadata" in props:
            meta = props.get("Metadata")
            self.title = self._format(meta)
            if isinstance(meta, dict):
                #  Players deliver the whole Metadata dict when the track
                #  changes, so both keys land in the same PropertiesChanged.
                self.art_url = str(meta.get("mpris:artUrl") or "")
                self.trackid = str(meta.get("mpris:trackid") or "")
        if "PlaybackStatus" in props:
            self.status = props["PlaybackStatus"] or "Stopped"
        for key, attr in (("CanGoNext", "can_next"),
                          ("CanGoPrevious", "can_prev"),
                          ("CanControl", "can_control")):
            if key in props:
                setattr(self, attr, bool(props[key]))
        self.changed.emit()

    @staticmethod
    def _format(meta):
        """"Artist - Title", or whatever subset of it exists.  Not truncated:
        the widget scrolls what does not fit rather than cutting it, which is
        the whole reason the old shell backend's `printf '%.24s'` is gone."""
        if not isinstance(meta, dict):
            return ""
        title = meta.get("xesam:title") or ""
        artist = meta.get("xesam:artist") or ""
        if isinstance(artist, (list, tuple)):
            artist = ", ".join(str(a) for a in artist if a)
        title, artist = str(title).strip(), str(artist).strip()
        if title and artist:
            return "%s - %s" % (artist, title)
        if title:
            return title
        url = meta.get("xesam:url") or ""
        if url:
            return os.path.basename(str(url))
        return ""

    #  -- signals in --

    @pyqtSlot(QDBusMessage)
    def _on_props(self, msg):
        args = msg.arguments()
        if len(args) < 2 or args[0] != PLAYER_IFACE:
            return
        changed = args[1] if isinstance(args[1], dict) else {}
        if self.owner and msg.service() == self.owner:
            self._apply(changed)
            return
        #  Somebody else on the bus.  Hand over only if they have started
        #  playing while ours is idle, or if we had nobody at all -- rescan
        #  rather than trusting the sender, because it decides by status.
        if self.service is None or (changed.get("PlaybackStatus") == "Playing"
                                    and self.status != "Playing"):
            self.rescan()

    @pyqtSlot(QDBusMessage)
    def _on_name_owner(self, msg):
        args = msg.arguments()
        if not args or not str(args[0]).startswith(MPRIS_PREFIX):
            return
        self.rescan()

    #  -- transport out --

    def _call(self, method):
        if not self.service:
            return
        QDBusInterface(self.service, MPRIS_PATH, PLAYER_IFACE,
                       self.bus).asyncCall(method)

    def play_pause(self):
        self._call("PlayPause")

    def stop(self):
        self._call("Stop")

    def next(self):
        self._call("Next")

    def previous(self):
        self._call("Previous")


#  ---- Sink volume ----------------------------------------------------------

class Sink(QObject):
    """Default sink volume, event-driven.

    `pactl subscribe` is a long-lived stream, not a poll: it says nothing
    until something on the server actually changes, and only then do we ask
    wpctl what the new value is.  That is the difference that matters -- the
    old widget asked once a second whether anything had happened.

    libpulse's own pa_context_subscribe() through python3-pulsectl would drop
    the two subprocesses, but pulsectl is not installed here and there is no
    compiler on this box to build anything that needs one.  pactl and wpctl
    are already hard dependencies of the shelf.
    """

    changed = pyqtSignal()
    outputs_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.volume = 0.0
        self.muted = False
        self.outputs = []
        self.target = "@DEFAULT_SINK@"

        #  Coalesces a burst of server events into one read: changing the
        #  volume emits several in a row and they all want the same answer.
        self._coalesce = QTimer(self)
        self._coalesce.setSingleShot(True)
        self._coalesce.setInterval(30)
        self._coalesce.timeout.connect(self._refresh)

        self._reader = QProcess(self)
        self._reader.finished.connect(self._reader_done)
        self._outputs_reader = QProcess(self)
        self._outputs_reader.finished.connect(self._outputs_done)

        self._stopping = False
        self._sub = QProcess(self)
        self._sub.readyReadStandardOutput.connect(self._on_events)
        self._sub.finished.connect(self._sub_died)
        self._start_sub()
        self._refresh()

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def _start_sub(self):
        self._sub.start("pactl", ["subscribe"])

    def _sub_died(self):
        if self._stopping:
            return
        #  pipewire-pulse restarting takes the subscription with it.  Come
        #  back for it rather than going silently deaf.
        QTimer.singleShot(2000, self._start_sub)

    def stop(self):
        """Reap the children before the panel goes.

        config restarts the panel on every fvwm Restart, so this is now the
        ordinary exit path rather than a rare one, and a subscription left
        running is a subscription left running *per restart* -- there were
        three orphaned `pactl subscribe` processes in ps when this was
        written.  The _stopping flag is what stops _sub_died reading its own
        termination as pipewire dying and resurrecting it."""
        self._stopping = True
        for proc in (self._sub, self._reader, self._outputs_reader):
            if proc.state() == QProcess.ProcessState.NotRunning:
                continue
            proc.terminate()
            if not proc.waitForFinished(300):
                proc.kill()

    def _on_events(self):
        data = bytes(self._sub.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.splitlines():
            if "on sink" in line or "on server" in line:
                self._coalesce.start()
                return

    def _read(self):
        if self._reader.state() != QProcess.ProcessState.NotRunning:
            #  A read is already in flight; its result will be current enough,
            #  and another event will re-arm us if it is not.
            return
        self._reader.start(
            "wpctl", ["get-volume", self.target])

    def _read_outputs(self):
        if self._outputs_reader.state() != QProcess.ProcessState.NotRunning:
            return
        self._outputs_reader.start("wpctl", ["status"])

    def _refresh(self):
        self._read()
        self._read_outputs()

    def _reader_done(self):
        out = bytes(self._reader.readAllStandardOutput()).decode("utf-8", "replace")
        m = re.search(r"Volume:\s*([0-9.]+)", out)
        if not m:
            return
        volume = float(m.group(1))
        muted = "MUTED" in out
        if volume != self.volume or muted != self.muted:
            self.volume, self.muted = volume, muted
            self.changed.emit()

    @staticmethod
    def _parse_outputs(text):
        outputs = []
        in_sinks = False
        for line in text.splitlines():
            section = re.sub(r"^[\s│├└─]+", "", line).strip()
            if section == "Sinks:":
                in_sinks = True
                continue
            if section in ("Sources:", "Streams:", "Clients:", "Filters:"):
                in_sinks = False
            if not in_sinks:
                continue
            match = re.match(r"^\s*(?:[│├└─]\s*)*(\*)?\s*(\d+)\.\s+(.+?)\s*$",
                             line)
            if not match:
                continue
            label = re.sub(r"(?:\s+\[[^]]+\])+$", "", match.group(3))
            outputs.append((int(match.group(2)), label,
                            bool(match.group(1))))
        return outputs

    def _outputs_done(self):
        out = bytes(self._outputs_reader.readAllStandardOutput()).decode(
            "utf-8", "replace")
        outputs = self._parse_outputs(out)
        default = next((node_id for node_id, _label, is_default in outputs
                        if is_default), None)
        self.target = str(default) if default is not None else "@DEFAULT_SINK@"
        if outputs != self.outputs:
            self.outputs = outputs
            self.outputs_changed.emit()

    #  -- writing --

    def set_volume(self, fraction):
        #  -l 1.0 caps it: pipewire will happily amplify past 100% and it
        #  sounds terrible.
        QProcess.startDetached("wpctl", ["set-volume", "-l", "1.0",
                                         self.target,
                                         "%.2f" % max(0.0, min(1.0, fraction))])

    def toggle_mute(self):
        QProcess.startDetached("wpctl", ["set-mute", self.target, "toggle"])

    def set_default_output(self, node_id):
        self.target = str(node_id)
        QProcess.startDetached("wpctl", ["set-default", str(node_id)])
        QTimer.singleShot(200, self._refresh)


#  ---- Cover art ----------------------------------------------------------

class CoverArt(QObject):
    """The current track's artwork, fetched on demand and held briefly.

    Request/response rather than a poll: a fetch starts when MPRIS names a
    new track and ends when its image lands or its guard timer expires.
    file://, bare paths and http(s) all go through one
    QNetworkAccessManager call; anything else (mpris-proxy's coverart://)
    is treated as no art.  A failed fetch keeps the last good pixmap up --
    the well would flash if every broken link blanked it -- and a reply
    that arrives after the track has moved on is dropped by its
    (service, trackid, url) tag.
    """

    changed = pyqtSignal()

    MAX_PIXELS = 1024    # decode cap: a 4000px cover must not balloon the panel
    CACHE = 8            # LRU entries, url -> pixmap
    TIMEOUT_MS = 8000    # per-request abort guard

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nav = QNetworkAccessManager(self)
        self._nav.finished.connect(self._on_reply)
        self._state = None     # the (service, trackid, url) currently served
        self._pixmap = None    # what the well currently shows
        self._cache = {}       # url -> QPixmap, oldest first
        self._timers = {}      # reply -> abort guard
        self._tags = {}        # reply -> the state it was made under

    @property
    def pixmap(self):
        return self._pixmap

    def set_track(self, service, trackid, art_url):
        """MPRIS just named a track (or nothing).  Fetch, swap, or clear."""
        url = str(art_url or "")
        if service and url and "://" not in url and not url.startswith("/"):
            url = os.path.abspath(url)
        if service and url and "://" not in url:
            url = QUrl.fromLocalFile(url).toString()
        state = (service, str(trackid or ""), url)
        if state == self._state:
            return
        self._state = state
        if not url:
            #  No player, no artUrl: the source says the art is gone.
            self._show(None)
            return
        if url in self._cache:
            self._cache[url] = self._cache.pop(url)   # most-recent last
            self._show(self._cache[url])
            return
        if QUrl(url).scheme() not in ("file", "http", "https"):
            #  Opaque schemes: there is no standard client-side resolver.
            self._show(None)
            return
        self._start(url)

    def _start(self, url):
        reply = self._nav.get(QNetworkRequest(QUrl(url)))
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(self.TIMEOUT_MS)
        timer.timeout.connect(lambda: reply.abort())
        self._timers[reply] = timer
        self._tags[reply] = self._state

    def _on_reply(self, reply):
        timer = self._timers.pop(reply, None)
        if timer is not None:
            timer.stop()
        tag = self._tags.pop(reply, None)
        if tag != self._state:
            #  The track moved on while this was in flight.
            reply.deleteLater()
            return
        data = bytes(reply.readAll())
        reply.deleteLater()
        if not data:
            #  Timeout or empty body: the last good art stays up.
            return
        buf = QBuffer(self)
        buf.setData(data)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buf)
        image = reader.read()
        buf.close()
        if not image.isNull() and max(image.width(), image.height()) > self.MAX_PIXELS:
            image = image.scaled(self.MAX_PIXELS, self.MAX_PIXELS,
                                 Qt.AspectRatioMode.KeepAspectRatio)
        if image.isNull():
            #  Decoding failed the same way: keep what is up.
            return
        url = tag[2]
        self._cache[url] = QPixmap.fromImage(image)
        while len(self._cache) > self.CACHE:
            self._cache.pop(next(iter(self._cache)))
        self._show(self._cache[url])

    def _show(self, pixmap):
        if pixmap is not self._pixmap:
            self._pixmap = pixmap
            self.changed.emit()


#  ---- PiP monitor ----------------------------------------------------------

class PipMonitor(QObject):
    """A browser's PiP window, found by geometry and owner.

    There is no X event for "a PiP appeared", so this is a deliberate
    poll, the same find loop shape photon_tray uses to adopt stalonetray.
    New candidates are admitted by shape, owner and type: a managed
    top-level that is video-shaped, whose _NET_WM_PID is a browser, and
    whose _NET_WM_WINDOW_TYPE is not NORMAL -- that last check is what
    keeps a tiled or floating main browser window out of the gate.  fvwm
    reparents every top-level into its own frame, so _NET_CLIENT_LIST
    (client ids) is the enumeration, not a root query_tree.

    Admission is sticky: the well the embed places a window in can be
    smaller than the gate, so a re-gated poll would drop the window we
    are holding and stop tracking it.  An admitted window is followed
    by identity -- a liveness probe, no gate -- until it dies or its
    embed keeps failing (give_up).
    """

    INTERVAL_MS = 1500

    W_MIN, W_MAX = 160, 1000       # plausible PiP widths
    H_MIN, H_MAX = 90, 700
    R_MIN, R_MAX = 1.2, 2.6        # video-ish aspect only
    BROWSERS = ("firefox", "chromium", "chrome")

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.dpy = display.Display()
        except (xerror.DisplayConnectionError, xerror.DisplayNameError):
            self.dpy = None
        self.window_id = None
        self.width = 0
        self.height = 0
        self._win = None           # the Xlib window of the current PiP
        self._dead = set()         # ids whose embed kept failing
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        if self.dpy is not None:
            self._timer.start()

    def give_up(self, xid):
        """The widget could not embed this window; stop re-offering it."""
        self._dead.add(xid)

    @staticmethod
    def _comm(pid):
        try:
            with open(f"/proc/{pid}/comm") as f:
                return f.read().strip()
        except OSError:
            return ""

    def _wm_pid(self, win):
        try:
            atom = self.dpy.intern_atom("_NET_WM_PID")
            prop = win.get_full_property(atom, X.AnyPropertyType)
            return prop.value[0] if prop else None
        except xerror.XError:
            return None

    def _is_normal_toplevel(self, win):
        """True for a browser's own main window, which always reports
        _NET_WM_WINDOW_TYPE_NORMAL. A real PiP popup never does (Firefox
        sets UTILITY); without this, an ordinary tiled or floating browser
        window that happens to land in the geometry gate gets reparented
        into the well in its place."""
        try:
            atom = self.dpy.intern_atom("_NET_WM_WINDOW_TYPE")
            normal = self.dpy.intern_atom("_NET_WM_WINDOW_TYPE_NORMAL")
            prop = win.get_full_property(atom, X.AnyPropertyType)
            return bool(prop) and normal in prop.value
        except xerror.XError:
            return False

    def _poll(self):
        if self.dpy is None:
            return
        found = self._tracked()
        if found is None:
            found = self._discover()
        self._set(found)

    def _tracked(self):
        """The already-admitted window, or None if it is gone or refused."""
        if (self.window_id is None or self.window_id in self._dead
                or self._win is None):
            return None
        try:
            g = self._win.get_geometry()
            return (self._win, g)
        except xerror.XError:
            return None

    def _discover(self):
        found = None
        try:
            root = self.dpy.screen().root
            atom = self.dpy.intern_atom("_NET_CLIENT_LIST")
            prop = root.get_full_property(atom, X.AnyPropertyType)
            wids = list(prop.value) if prop else []
        except xerror.XError:
            wids = []
        for wid in wids:
            try:
                win = self.dpy.create_resource_object("window", wid)
                g = win.get_geometry()
            except xerror.XError:
                continue
            if not (self.W_MIN <= g.width <= self.W_MAX
                    and self.H_MIN <= g.height <= self.H_MAX):
                continue
            if not (self.R_MIN <= g.width / g.height <= self.R_MAX):
                continue
            if self._is_normal_toplevel(win):
                continue
            pid = self._wm_pid(win)
            if pid is None or pid in self._dead:
                continue
            if self._comm(pid) not in self.BROWSERS:
                continue
            found = (win, g)
            break
        return found

    def _set(self, found):
        xid = found[0].id if found else None
        size = (found[1].width, found[1].height) if found else (0, 0)
        if xid == self.window_id and size == (self.width, self.height):
            return
        self._dead.discard(self.window_id)
        self._win = found[0] if found else None
        self.window_id = xid
        self.width, self.height = size
        self.changed.emit()


#  ---- The widget -----------------------------------------------------------

PREV, STOP, PLAY, NEXT = range(4)

#  Media body, header excluded.
NATURAL_H = 100

#  Everything below is measured off ~/Desktop/qnx621-1-1.png rather than
#  guessed, columns at x=900/920 and rows at y=589.  The reference shelf is
#  134px inner against our 152, so heights transfer 1:1 and only the widths
#  that span the shelf grow.
FIELD_H = 19          # title field, 16px interior inside its bevel
BTN_H, BTN_GAP = 22, 2
GAP = 3               # field to buttons, buttons to divider, divider to volume
THUMB_W, THUMB_H = 10, 17
GROOVE_DROP = 6       # groove top below thumb top


class _OutputBox(QComboBox):
    #  QSS can't build the wedge out of borders -- that rule rendered a
    #  solid bar, not an arrow -- so the glyph is painted.
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        cx, cy = self.width() - 8, self.height() // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(photon.INK)
        p.drawPolygon(QPolygon([QPoint(cx - 4, cy - 2), QPoint(cx + 4, cy - 2),
                                QPoint(cx, cy + 3)]))


class MediaWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, photon.FACE)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self.font_title = photon.font(8)
        self.font_glyph = photon.font(8)

        self.mpris = Mpris(self)
        self.mpris.changed.connect(self._on_mpris)
        self.sink = Sink(self)
        self.sink.changed.connect(self._on_sink)
        self.sink.outputs_changed.connect(self._on_outputs)
        self.cover = CoverArt(self)
        self.cover.changed.connect(self._on_cover)
        self.pip = PipMonitor(self)
        self.pip.changed.connect(self._on_pip)
        self._pip_xid = None      # the PiP window reparented into this one
        self._pip_geom = None     # last geometry sent, so embed + the
                                  # standalone resize it triggers cannot
                                  # issue it twice
        self._has_art = False    # the well is up; a flip or a side change relays
        self._side = None        # the side the last natural_height_changed was for
        #  Mpris already rescan'd during its own __init__ -- before this
        #  connect existed -- so a track that loaded while the player was
        #  paused (or the panel restarted mid-play) would never emit.
        self.cover.set_track(self.mpris.service, self.mpris.trackid,
                             self.mpris.art_url)

        self.output = _OutputBox(self)
        self.output.setFont(photon.font(8))
        self.output.setMaxVisibleItems(8)
        self.output.setStyleSheet("""
            QComboBox {
                background: %s; color: %s; border: 1px solid %s;
                padding: 0 16px 0 3px;
            }
            QComboBox::drop-down { border-left: 1px solid %s; width: 15px; }
            QComboBox QAbstractItemView {
                background: %s; color: %s; border: 1px solid %s;
                selection-background-color: %s; selection-color: %s;
            }
        """ % (photon.FIELD.name(), photon.INK.name(), photon.DARK.name(),
               photon.DARK.name(), photon.FIELD.name(),
               photon.INK.name(), photon.DARK.name(), photon.HEADER.name(),
               photon.INK.name()))
        self.output.currentIndexChanged.connect(self._choose_output)

        self._pressed = None          # transport button held down
        self._dragging = False        # slider thumb held
        self._drag_value = 0.0
        self._scroll = 0              # marquee offset, pixels
        self._scroll_span = 0         # width of one title+separator cycle

        self._marquee = QTimer(self)
        self._marquee.setInterval(MARQUEE_MS)
        self._marquee.timeout.connect(self._tick)

        #  Volume writes are coalesced: a drag crosses a hundred pixels and
        #  each one would otherwise be a wpctl spawn.
        self._pending = None
        self._flush = QTimer(self)
        self._flush.setSingleShot(True)
        self._flush.setInterval(40)
        self._flush.timeout.connect(self._flush_volume)

        #  The panel is resizable and this reflows to whatever it is given.
        self.resize(photon.SHELF_INNER, NATURAL_H)
        self.setMinimumSize(110, 60)
        self._relayout()
        self._on_outputs()

    #  -- geometry --
    #
    #  Recomputed from the current size rather than baked in, because
    #  FvwmButtons resizes a swallowed window to its cell and a widget laid
    #  out at fixed positions clips instead of reflowing.

    #  Every rect below the width, in one place: _relayout and
    #  natural_height both read this, so with a variable side there is no
    #  second copy of the arithmetic to drift.
    def _layout(self, w, side):
        pad = 4
        r_output = QRect(pad, pad, w - 2 * pad, FIELD_H)
        y0 = r_output.bottom() + 1 + GAP
        if side is None:
            r_art, art_div_y = None, None
            r_title = QRect(pad, y0, w - 2 * pad, FIELD_H)
        else:
            r_art = QRect(pad, y0, w - 2 * pad, side)
            art_div_y = r_art.bottom() + 1 + GAP
            r_title = QRect(pad, art_div_y + 2 + GAP, w - 2 * pad, FIELD_H)
        by = r_title.bottom() + 1 + GAP
        row_w = max(4, w - 2 * pad - 3 * BTN_GAP)
        button_w, extra = divmod(row_w, 4)
        r_buttons, bx = [], pad
        for i in range(4):
            bw = button_w + (1 if i < extra else 0)
            r_buttons.append(QRect(bx, by, bw, BTN_H))
            bx += bw + BTN_GAP
        div_y = by + BTN_H + GAP
        thumb_top = div_y + 2 + GAP
        return {"pad": pad, "r_art": r_art, "art_div_y": art_div_y,
                "r_title": r_title, "r_buttons": r_buttons, "div_y": div_y,
                "r_speaker": QRect(6, thumb_top + 1, 16, 16),
                "r_groove": QRect(32, thumb_top + GROOVE_DROP,
                                  max(20, w - 28 - 32), 5),
                "thumb_top": thumb_top, "r_ticks_y": thumb_top + THUMB_H - 1,
                "r_output": r_output,
                "content_bottom": thumb_top + THUMB_H}

    def _well_side(self, w):
        """The well's side for the current source, or None: full width,
        shortened by the source's own ratio, capped at the square."""
        well_w = w - 8
        if self._pip_xid is not None:
            #  The monitor only reports a PiP that passed its geometry
            #  gate, so both dimensions are > 0 here.
            return min(well_w, round(well_w * self.pip.height /
                                     self.pip.width))
        pm = self.cover.pixmap
        if pm is None or pm.isNull():
            return None
        return min(well_w, round(well_w * pm.height() / pm.width()))

    def _relayout(self):
        w = self.width()
        #  FvwmButtons' module-wide `Padding 4 0` does not reach a swallowed
        #  window -- it resizes the child to the whole cell -- so the inset
        #  that keeps this row in line with the meters above it has to come
        #  from here.
        L = self._layout(w, self._well_side(w))
        self.r_art = L["r_art"]
        self.art_div_y = L["art_div_y"]
        self.r_title = L["r_title"]
        self.r_buttons = L["r_buttons"]
        self.div_y = L["div_y"]
        self.r_speaker = L["r_speaker"]
        self.r_groove = L["r_groove"]
        self.r_thumb_top = L["thumb_top"]
        self.r_ticks_y = L["r_ticks_y"]
        self.r_output = L["r_output"]
        self.output.setGeometry(self.r_output)
        self._measure_title()

    def _refresh_well(self):
        side = self._well_side(self.width())
        if side == self._side:
            self.update()      # track-to-track swap: repaint the same rect
            return
        self._side = side
        self._has_art = side is not None
        self._relayout()
        self.natural_height_changed.emit()
        self.update()
        if self.parent() is None:
            #  Standalone window: nothing else grows or shrinks it.
            self.resize(self.width(), self.natural_height(self.width()))

    def sizeHint(self):
        return QSize(photon.SHELF_INNER, NATURAL_H)

    natural_height_changed = pyqtSignal()

    def natural_height(self, w):
        side = self._well_side(w)
        if side is None:
            return NATURAL_H
        #  +4: the slack the no-well state leaves below the volume row
        #  (content bottom is side+106; square well side = w-8, so the
        #  square case lands on w+102).
        return self._layout(w, side)["content_bottom"] + 4

    def resizeEvent(self, event):
        self._relayout()
        side = self._well_side(self.width())
        if side != self._side:
            self._side = side
            self.natural_height_changed.emit()
        self._position_pip()

    #  -- state in --

    def _on_mpris(self):
        self.cover.set_track(self.mpris.service, self.mpris.trackid,
                             self.mpris.art_url)
        self._measure_title()
        self.update()

    #  The monitor found (or lost) a PiP window.  The window becomes a child
    #  of this widget's own X window and is placed on the well; no frame, no
    #  repaint trickery -- the browser keeps drawing it exactly where the
    #  cover art would sit.
    def _on_pip(self):
        xid = self.pip.window_id
        if xid is None:
            if self._pip_xid is not None:
                self._pip_xid = None
                self._pip_geom = None
                self._refresh_well()
            return
        if xid != self._pip_xid:
            self._embed_pip(xid)
        if self._pip_xid is None:
            return
        self._refresh_well()
        self._position_pip()

    def _embed_pip(self, xid):
        try:
            #  winId() is a sip voidptr in PyQt6, not an int: Xlib's
            #  request packing rejects it.
            self.pip._win.reparent(int(self.winId()), 0, 0)
        except xerror.XError:
            #  The window refuses the move (input-class or visual mismatch,
            #  or it died between the poll and now): leave it floating and
            #  stop re-offering.
            self.pip.give_up(xid)
            return
        self._pip_xid = xid
        self._pip_geom = None

    def _position_pip(self):
        #  Child coordinates are relative to our window; r_art is in the
        #  same space.
        if self._pip_xid is None or self.r_art is None:
            return
        r = self.r_art
        if (r.x(), r.y(), r.width(), r.height()) == self._pip_geom:
            return
        self._pip_geom = (r.x(), r.y(), r.width(), r.height())
        try:
            self.pip._win.configure(x=r.x(), y=r.y(),
                                    width=r.width(), height=r.height())
        except xerror.XError:
            pass

    def _on_sink(self):
        if not self._dragging:
            self.update(self._vol_band())

    def _on_outputs(self):
        with QSignalBlocker(self.output):
            self.output.clear()
            if not self.sink.outputs:
                self.output.addItem("No output device")
                self.output.setEnabled(False)
                self.output.setToolTip("")
                self._publish_output("@DEFAULT_SINK@")
                return
            self.output.setEnabled(True)
            selected = 0
            for i, (node_id, label, is_default) in enumerate(self.sink.outputs):
                self.output.addItem(label, node_id)
                if is_default:
                    selected = i
            self.output.setCurrentIndex(selected)
            self.output.setToolTip(self.output.currentText())
            self._publish_output(self.output.currentData())

    def _choose_output(self, index):
        node_id = self.output.itemData(index)
        if node_id is not None:
            self.sink.set_default_output(node_id)
            self._publish_output(node_id)

    @staticmethod
    def _publish_output(node_id):
        QProcess.startDetached(
            "FvwmCommand", ["InfoStoreAdd media_output %s" % node_id])

    def _vol_band(self):
        top = self.r_thumb_top - 1
        return QRect(0, top, self.width(), THUMB_H + 4)

    #  -- marquee --

    def _title_text(self):
        return self.mpris.title or ("No player" if not self.mpris.service
                                    else "—")

    def _measure_title(self):
        fm = QFontMetrics(self.font_title)
        avail = photon.sunken_interior(self.r_title).width() - 6
        text = self._title_text()
        if fm.horizontalAdvance(text) <= avail:
            self._scroll_span = 0
            self._scroll = 0
            self._marquee.stop()
        else:
            self._scroll_span = fm.horizontalAdvance(text + MARQUEE_SEP)
            self._scroll = 0
            self._marquee.start()

    def _tick(self):
        self._scroll = (self._scroll + 1) % max(1, self._scroll_span)
        #  Only the field repaints.  Qt double-buffers, so this is a blit, not
        #  a clear-then-draw -- the thing FvwmScript could not do.
        self.update(self.r_title)

    #  -- painting --

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), photon.FACE)
        if self.r_art is not None:
            self._paint_art(p)
            photon.divider(p, self.art_div_y, 2, self.width() - 3)
        self._paint_title(p)
        self._paint_transport(p)
        photon.divider(p, self.div_y, 2, self.width() - 3)
        self._paint_volume(p)

    def _paint_title(self, p):
        photon.sunken(p, self.r_title, photon.FIELD)
        inner = photon.sunken_interior(self.r_title)
        p.save()
        p.setClipRect(inner)
        p.setFont(self.font_title)
        p.setPen(photon.INK if self.mpris.title else photon.INK_OFF)
        fm = QFontMetrics(self.font_title)
        baseline = inner.top() + (inner.height() + fm.capHeight()) // 2
        text = self._title_text()
        if self._scroll_span:
            x = inner.left() + 3 - self._scroll
            p.drawText(x, baseline, text + MARQUEE_SEP)
            p.drawText(x + self._scroll_span, baseline, text + MARQUEE_SEP)
        else:
            p.drawText(inner.left() + 3, baseline, text)
        p.restore()

    def _on_cover(self):
        self._refresh_well()

    def _paint_art(self, p):
        photon.trough(p, self.r_art)
        if self._pip_xid is None:
            r = self.r_art.adjusted(4, 4, -4, -4)
            art = self.cover.pixmap.scaled(
                r.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            x = r.left() + (r.width() - art.width()) // 2
            y = r.top() + (r.height() - art.height()) // 2
            p.drawPixmap(x, y, art)

    def _paint_transport(self, p):
        live = self.mpris.service is not None
        enabled = (live and self.mpris.can_prev, live, live,
                   live and self.mpris.can_next)
        playing = self.mpris.status == "Playing"
        for i, r in enumerate(self.r_buttons):
            down = self._pressed == i
            photon.button(p, r, down)
            #  A held button moves its glyph one pixel down and right, which
            #  is the whole of Photon's press animation.
            g = r.translated(1, 1) if down else r
            self._glyph(p, i, g, enabled[i], playing)

    def _glyph(self, p, which, r, enabled, playing):
        c = photon.INK if enabled else photon.INK_OFF
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        cx, cy = r.center().x(), r.center().y()

        #  Sizes taken off the reference rather than chosen: the stop is a
        #  7px square and a triangle is 5 wide by 7 tall.  The glyphs stay
        #  compact even though their buttons expand to fill the shelf.
        def tri(x, left):
            if left:
                pts = [QPoint(x + 5, cy - 3), QPoint(x + 5, cy + 4), QPoint(x, cy)]
            else:
                pts = [QPoint(x, cy - 3), QPoint(x, cy + 4), QPoint(x + 5, cy)]
            p.drawPolygon(QPolygon(pts))

        #  Rewind and fast-forward, not skip-to-start and skip-to-end: the
        #  reference's outer buttons are bare double triangles with no bar
        #  against them.
        if which == PREV:
            tri(cx - 6, True)
            tri(cx - 1, True)
        elif which == STOP:
            p.drawRect(QRect(cx - 3, cy - 3, 7, 7))
        elif which == PLAY:
            if playing:
                p.drawRect(QRect(cx - 3, cy - 3, 2, 7))
                p.drawRect(QRect(cx + 1, cy - 3, 2, 7))
            else:
                p.drawPolygon(QPolygon([QPoint(cx - 2, cy - 3),
                                        QPoint(cx - 2, cy + 4),
                                        QPoint(cx + 3, cy)]))
        elif which == NEXT:
            tri(cx - 4, False)
            tri(cx + 1, False)
        p.restore()

    def _paint_volume(self, p):
        value = self._value()
        muted = self.sink.muted
        name = ("audio-volume-muted" if muted or value <= 0.001 else
                "audio-volume-low" if value < 0.34 else
                "audio-volume-medium" if value < 0.67 else
                "audio-volume-high")
        if not photon.draw_icon(p, name, self.r_speaker, not muted):
            #  No icon theme: a filled wedge is better than an empty hole.
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(photon.INK if not muted else photon.INK_OFF)
            r = self.r_speaker
            p.drawPolygon(QPolygon([
                QPoint(r.left() + 2, r.center().y() - 3),
                QPoint(r.left() + 6, r.center().y() - 3),
                QPoint(r.left() + 11, r.top() + 2),
                QPoint(r.left() + 11, r.bottom() - 2),
                QPoint(r.left() + 6, r.center().y() + 3),
                QPoint(r.left() + 2, r.center().y() + 3)]))
            p.restore()

        photon.groove(p, self.r_groove)

        #  Five marks under the groove, ends included.  The reference's are
        #  spaced ~18.5px across an 86px groove, which is this same rule at
        #  its width rather than a fixed pitch.
        travel = self.r_groove.width() - THUMB_W
        for i in range(5):
            x = self.r_groove.left() + THUMB_W // 2 + round(travel * i / 4)
            photon.tick(p, x, self.r_ticks_y)

        thumb_x = self.r_groove.left() + round(travel * value)
        photon.thumb(p, QRect(thumb_x, self.r_thumb_top, THUMB_W, THUMB_H))

    def _value(self):
        return self._drag_value if self._dragging else self.sink.volume

    #  -- input --

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()

        for i, r in enumerate(self.r_buttons):
            if r.contains(pos):
                self._pressed = i
                self.update(r)
                return

        if self.r_speaker.contains(pos):
            self.sink.toggle_mute()
            return

        band = QRect(self.r_groove.left() - 6, self.r_thumb_top - 2,
                     self.r_groove.width() + 12, THUMB_H + 4)
        if band.contains(pos):
            self._dragging = True
            self._drag_value = self.sink.volume
            self._set_from_x(pos.x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._set_from_x(event.position().toPoint().x())
        elif self._pressed is not None:
            inside = self.r_buttons[self._pressed].contains(
                event.position().toPoint())
            if not inside:
                r = self.r_buttons[self._pressed]
                self._pressed = None
                self.update(r)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._flush_volume()
            self.update(self._vol_band())
            return
        if self._pressed is None:
            return
        which, self._pressed = self._pressed, None
        r = self.r_buttons[which]
        self.update(r)
        if not r.contains(event.position().toPoint()):
            return
        if which == PREV and self.mpris.can_prev:
            self.mpris.previous()
        elif which == STOP:
            self.mpris.stop()
        elif which == PLAY:
            self.mpris.play_pause()
        elif which == NEXT and self.mpris.can_next:
            self.mpris.next()

    def wheelEvent(self, event):
        step = 0.05 if event.angleDelta().y() > 0 else -0.05
        target = max(0.0, min(1.0, self.sink.volume + step))
        self.sink.set_volume(target)

    def _set_from_x(self, x):
        travel = self.r_groove.width() - THUMB_W
        value = (x - self.r_groove.left() - THUMB_W / 2.0) / float(max(1, travel))
        value = max(0.0, min(1.0, value))
        if abs(value - self._drag_value) < 0.005:
            return
        self._drag_value = value
        self._pending = value
        if not self._flush.isActive():
            self._flush.start()
        self.update(self._vol_band())

    def _flush_volume(self):
        if self._pending is None:
            return
        self.sink.set_volume(self._pending)
        self._pending = None


def main():
    app = QApplication(sys.argv)
    #  WM_CLASS: instance comes from argv[0], class from here.  Handy for
    #  xdotool and for a Style rule, and harmless to the Swallow, which hangs
    #  on the title.
    app.setApplicationName("ShelfMedia")
    app.setDesktopFileName("ShelfMedia")

    w = MediaWidget()
    #  Title before show(): FvwmButtons' UseOld looks for the name at map
    #  time, and a window that renames itself afterwards is a window it has
    #  already decided about.
    w.setWindowTitle("ShelfMedia")
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
