"""The drag wheel must not become visible until Qt confirms a local file drop target."""
from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent
from PySide6.QtWidgets import QApplication

from dragshift import radial
from dragshift.radial import Item, RadialMenu
from dragshift.trigger import DragShiftWatcher


def qapp():
    return QApplication.instance() or QApplication([])


def test_shift_without_mouse_drag_does_not_open_menu():
    app = qapp()
    watcher = DragShiftWatcher(lambda: False, lambda: False, app)
    shown = []
    watcher.show_menu.connect(shown.append)
    watcher._state = lambda: (False, True, False)
    watcher._tick()
    assert not shown


def test_wheel_stays_hidden_for_text_and_opens_for_local_file(tmp_path, monkeypatch):
    app = qapp()
    monkeypatch.setattr(radial.glass, "hidden_drag_images",
                        lambda: nullcontext(SimpleNamespace(hwnds=[], info=[], rects=[])))
    menu = RadialMenu(lambda paths: {"Convert": [Item("MP3")]}, lambda _: "test file")
    menu._render = lambda _: None
    menu.popup(QPoint(300, 300))
    try:
        assert menu._waiting_for_file
        assert menu.windowOpacity() < 0.02

        text = QMimeData()
        text.setText("selected text")
        event = QDragEnterEvent(QPoint(80, 80), Qt.CopyAction, text, Qt.LeftButton, Qt.ShiftModifier)
        menu.dragEnterEvent(event)
        assert not event.isAccepted()
        assert menu.windowOpacity() < 0.02

        path = tmp_path / "clip.mp4"
        path.write_bytes(b"file placeholder")
        files = QMimeData()
        files.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDragEnterEvent(QPoint(80, 80), Qt.CopyAction, files, Qt.LeftButton, Qt.ShiftModifier)
        menu.dragEnterEvent(event)
        app.processEvents()
        assert event.isAccepted()
        assert menu.got_drag
        assert not menu._waiting_for_file
        assert menu.windowOpacity() == 1.0
    finally:
        menu.close_menu()
