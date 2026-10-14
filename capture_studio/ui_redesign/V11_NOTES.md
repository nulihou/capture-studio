# Capture Studio v11 (0.11.0) — copied from v10 incl. audit fixes; v10 untouched

## Icon status pills
- New `Pill` widget (window.py): Lucide icon + label, semantic kinds neutral/ok/info/warn/error/rec/live/idle.
  Title chip (未连接 / board name), preview badge (空闲 / 实时预览中 / 录制中) and the PC camera pick reason are now pills.
  Rec/live/neutral use a crisp painted dot; ok/info/warn/error use circle-check / info / triangle-alert / circle-x
  (12 px glyphs, rasterised per DPR and cached).
- The preview badge shows the recording countdown again ("录制中 · 42 秒"). In v10 `word_text` was computed but never shown.
- The chip no longer calls setStyleSheet on every 200 ms refresh; the style only changes when the kind changes.
## Health dialog
- Text marks ✓ / ! / ✕ replaced by circle-check / triangle-alert / circle-x icons (16 px, semantic colours, top-aligned with wrapped text).
## Motion (`motion.py`, QPropertyAnimation / QVariantAnimation)
- Page switch: inspector page fades in over 180 ms (OutCubic); the opacity effect is removed when it finishes, so idle cost is zero.
- Pill colour/state change: 200 ms cross-fade (snapshot of the old state fades out over the new one).
- Collapsible sections: manual mode row and custom exposure animate maximumHeight over 160 ms.
- Toast: in-window toast for notifications (fade in 180 ms, hold 2.6 s, fade out 260 ms), click-through. The tray balloon is kept.
- Hover/press feedback: QSS states from v10 (nav/inputs/lists/buttons).
- Reduced motion: settings checkbox "减少动态效果" (`reduced_motion`), env `CAPTURE_STUDIO_REDUCED_MOTION=1`, or Windows
  "Animate controls and elements" off (SPI_GETCLIENTAREAANIMATION). Every helper then jumps straight to the final state.
## Tests (PC, offscreen; Tk test_ui.py excluded)
- unit 161 OK (new tests/test_v11.py: reduced-motion sources, instant vs animated paths, effect cleanup, pill kinds/icons/cache).
- smoke 220/220 (new v11 checks: pills and kinds, crossfade, reduced → no ghost / no opacity effect, fade cleanup,
  toast, health icons without text marks, settings toggle, version 0.11.0).
- No on-screen launch for v11. Offscreen review shots: C:\Users\<user>\cs_ui\v11_shots_off\ (box /workspace/v11_shots_off/).
## Limitations
- No slide animation (only fade): moving pages inside the layout would re-layout every frame.
- Animations are not verified on screen yet (only offscreen, timing-based).
