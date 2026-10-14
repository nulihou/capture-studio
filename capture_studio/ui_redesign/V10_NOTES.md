# Capture Studio v10 — icon set & detail polish (copied from v9; v9 untouched)

## Icons
- One set: **Lucide** (lucide-static v1.56.0, ISC). 71 SVGs vendored in `assets/icons/` with `LICENSE` + `ATTRIBUTION.md`; no runtime network.
- `icons.py`: semantic names (nav.*, act.*, dev.*, st.*, ui.*) → SVG; rendered with QSvgRenderer at size×DPR
  (1 / 1.25 / 1.5 / 2) and tagged with devicePixelRatio, so they're sharp at 125 %. currentColor and stroke width are rewritten
  (optical strokes: 16 px 1.9, 20 px 1.75, 24 px 1.6). Roles normal/muted/active/accent/disabled/onAccent/ok/warn/error
  go through theme.color(), so light and dark both work. QIcon modes: Normal / Active (hover) / Selected / Disabled, plus an On state (blue when selected in the sidebar).
- Applied to: sidebar nav (20 px), wizard/shortcut links, every known action button (16 px, white on primary), Check
  and Templates buttons, overview tile captions (board/camera/stream/status), peripheral categories (white glyph on a
  coloured rounded tile, replacing the CAM/TTY text badges), the "no signal" empty state (camera-off), the combo
  chevron (with an @2x twin), and the window, tray and status icons (badges: recording red, live green).
- App icon: white aperture on a blue squircle with a gradient. `assets/app.ico` (16–256, 9 sizes), `app.png`, `app_512.png`;
  build_portable bundles `assets/icons`, the hidden-import icons/QtSvg, and `--icon`.
## Detail polish
- Focus ring only on keyboard focus (TabFocus plus a blue border). Hover/pressed on nav, inputs and list items. Styled horizontal scrollbar,
  separator style, keycaps. Shortcut tooltips ("Preview Frame · P", "Connection wizard · Ctrl+K", etc.).
- Tabular figures (tnum) on the app font.
- Lab "Picture" tab blank area: a keyboard cheat-sheet (real bindings). Its height policy is Ignored and rows that don't fit
  are hidden, so 1280×800 never overflows.
- Footers with four buttons stay text-only so English labels never clip; "record" uses circle-dot.
## Tests
- New `tests/test_icons.py` (7 tests): files and license present, maps valid, every icon × 16/20/24 × 4 DPRs × light/dark renders
  with ink, colours differ by theme and state, QIcon has HiDPI variants, tiles and app icon render, the .ico exists, the chevron has an @2x twin.
- smoke_ui: added v10 checks (nav/action icons, primary glyphs, shortcut tooltips, peripheral tiles, window icon, key tips can't
  force height, no button narrower than icon + text in English, all referenced icons exist).
- PC (offscreen, test_ui.py excluded): unit 137 OK, smoke 207/207.
## Limitations
- Status pills are still text-only (QLabel rich-text images aren't reliably HiDPI); the health dialog keeps its ✓/! text marks.
- No transition animations (none are cheap in QSS).
- No PC camera present, so states that need a camera were not seen live.
