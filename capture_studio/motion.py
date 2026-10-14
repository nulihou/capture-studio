"""v11: restrained, Apple-like motion. Every helper is a no-op (instant final state) when reduced motion is on.

Reduced motion = settings["reduced_motion"] / env CAPTURE_STUDIO_REDUCED_MOTION=1 / Windows "Animate controls and
elements" turned off. Animations only touch opacity or maximumHeight, never re-layout every frame of large trees.
"""
from __future__ import annotations

import ctypes
import os
from typing import Any, Callable

PAGE_MS = 180
PILL_MS = 200
REVEAL_MS = 160
TOAST_IN_MS = 180
TOAST_OUT_MS = 260
TOAST_HOLD_MS = 2600

_override: bool | None = None


def system_reduced() -> bool:
    """Windows: SPI_GETCLIENTAREAANIMATION (0x1042) == FALSE means the user turned animations off."""
    if os.name != "nt":
        return False
    try:
        value = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0)
        return value.value == 0
    except Exception:
        return False


def set_reduced(value: bool | None) -> None:
    global _override
    _override = value


def reduced() -> bool:
    if _override is not None:
        return _override
    if os.environ.get("CAPTURE_STUDIO_REDUCED_MOTION", "") in ("1", "true", "yes"):
        return True
    return system_reduced()


def _keep(widget: Any, anim: Any) -> Any:
    store = widget.__dict__.setdefault("_motion", {})
    old = store.get(anim.objectName())
    if old is not None:
        old.stop()
    store[anim.objectName()] = anim
    return anim


def fade_in(widget: Any, ms: int = PAGE_MS, done: Callable[[], None] | None = None) -> None:
    """Opacity 0 -> 1, then the effect is removed so steady-state painting costs nothing."""
    from PySide6.QtCore import QEasingCurve, QPropertyAnimation
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    if reduced() or widget is None:
        if done:
            done()
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setObjectName("fade")
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def finish() -> None:
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
        if done:
            done()
    anim.finished.connect(finish)
    _keep(widget, anim).start()


def reveal(widget: Any, show: bool, ms: int = REVEAL_MS) -> None:
    """Collapsible section: animates maximumHeight; final state is plain setVisible()."""
    from PySide6.QtCore import QEasingCurve, QPropertyAnimation
    if widget.isVisible() == show and not widget.__dict__.get("_motion", {}).get("reveal"):
        widget.setVisible(show)
        return
    if reduced() or not widget.window().isVisible():
        widget.setMaximumHeight(16777215)
        widget.setVisible(show)
        return
    target = max(widget.sizeHint().height(), 1)
    anim = QPropertyAnimation(widget, b"maximumHeight", widget)
    anim.setObjectName("reveal")
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    if show:
        widget.setMaximumHeight(0)
        widget.setVisible(True)
        anim.setStartValue(0)
        anim.setEndValue(target)
    else:
        anim.setStartValue(widget.height())
        anim.setEndValue(0)

    def finish() -> None:
        widget.setMaximumHeight(16777215)
        widget.setVisible(show)
        widget.__dict__.get("_motion", {}).pop("reveal", None)
    anim.finished.connect(finish)
    _keep(widget, anim).start()
