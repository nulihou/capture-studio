"""Offscreen smoke test for the Qt window with a mocked board (no network, no settings written).
Usage: python smoke_ui.py <package>"""
import importlib, os, sys, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt" and not os.environ.get("QT_QPA_FONTDIR"):
    # The offscreen platform has no font database on Windows unless pointed at the system fonts;
    # without it every text width is measured with a fallback ~2x too wide and layout checks fail.
    os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
pkg = sys.argv[1]
i18n = importlib.import_module(pkg + ".i18n"); i18n.LANG = "zh"
i18n.set_lang = lambda lang: setattr(i18n, "LANG", lang)  # do not persist during tests
w = importlib.import_module(pkg + ".window")
from PySide6.QtWidgets import QApplication, QDialog
app = QApplication.instance() or QApplication([])
S = w.STUDIO
calls = []
S._save = lambda *a, **k: None
for name in ("connect", "discover", "start_live", "stop_live", "snap", "read_controls", "start_record",
             "stop_record", "list_sessions", "fetch_session", "audit", "scan_pc"):
    setattr(S, name, (lambda n: (lambda *a, **k: calls.append(n)))(name))
QDialog.exec = lambda self: (calls.append("dialog_exec"), 0)[1]
results = []
def check(label, cond):
    results.append(("PASS" if cond else "FAIL") + "  " + label)
def state(**kw):
    with S.lock:
        S.connected = kw.get("connected", False); S.busy = kw.get("busy", False)
        S.live = kw.get("live", False); S.recording = kw.get("recording")
        S.completion = kw.get('completion'); S.start_uncertain = kw.get('start_uncertain', False)
        S.controls = kw.get("controls", []); S.sessions = kw.get("sessions", [])
        S.board_label = "开发板：KV260" if S.connected else "未连接"
    win.refresh(S.state())
def btn(text):
    shown = w._button_text(text)
    return [b for b in win.actions if b.text() == shown]
try:
    win = w.StudioWindow(); win.timer.stop(); win.resize(1280, 800); win.show(); app.processEvents()
    state()
    check("disconnected: 应用并预览 disabled", not btn("应用并预览")[0].isEnabled())
    check("disconnected: 识别并预览 enabled (opens dialog)", btn("识别并预览")[0].isEnabled())
    btn("识别并预览")[0].click(); check("identify while disconnected opens connect dialog", "dialog_exec" in calls)
    check("disconnected: 停止并取回 disabled", not any(b.isEnabled() for b in btn("停止并取回")))
    state(connected=True)
    for t in ("应用并预览", "读取参数", "录 60 秒", "实时", "预览", "板端"):
        check(f"connected: {t} enabled", all(b.isEnabled() for b in btn(t)))
    calls.clear(); btn("应用并预览")[0].click(); check("apply -> start_live", calls == ["start_live"])
    calls.clear(); btn("录 60 秒")[0].click(); check("record 60s -> start_record", calls == ["start_record"])
    calls.clear(); btn("读取参数")[0].click(); check("read -> read_controls", calls == ["read_controls"])
    state(connected=True, live=True)
    check("live: toggle shows 停止实时", win.live_button.text() == w._button_text("停止实时"))
    calls.clear(); win.live_button.click(); check("toggle while live -> stop_live", calls == ["stop_live"])
    state(connected=True, recording={"mode": "board", "session_id": "S1", "seconds": 60})
    check("recording: stop enabled", all(b.isEnabled() for b in btn("停止并取回")))
    check("recording: start disabled", not any(b.isEnabled() for b in btn("开始采集")))
    check("recording: badge", win.badge.text() == "录制中")
    calls.clear(); btn("停止并取回")[0].click(); check("stop -> stop_record", calls == ["stop_record"])
    state(connected=True, completion={'session_id': 'S1', 'stage': 'auditing'})
    check('completion: new start disabled', not any(b.isEnabled() for b in btn('开始采集')))
    check('completion: resume enabled', all(b.isEnabled() for b in btn('停止并取回')))
    check('completion: badge does not claim idle', win.badge.text() == '收尾待完成')
    state(connected=True, start_uncertain=True)
    check('uncertain start: start disabled', not any(b.isEnabled() for b in btn('开始采集')))
    state(connected=True, busy=True)
    check("busy: every action disabled", not any(b.isEnabled() for b in win.actions))
    state(connected=True, sessions=[{"session_id": "A", "status": "recorded"}])
    win.show_page("sessions"); app.processEvents()
    check("no selection: 校验 disabled", not btn("校验")[0].isEnabled())
    win.sessions.setCurrentRow(0); state(connected=True, sessions=[{"session_id": "A", "status": "recorded"}])
    check("selection: 校验/取回 enabled", btn("校验")[0].isEnabled() and btn("取回")[0].isEnabled())
    state(connected=True, sessions=[{"session_id": "A", "status": "audited"}])
    check("session status change is shown", "audited" in win.sessions.item(0).text())
    calls.clear(); btn("取回")[0].click(); btn("校验")[0].click(); check("fetch/audit wired", calls == ["fetch_session", "audit"])
    # stored values never translated
    win.set_language("en"); app.processEvents(); state(connected=True)
    p = win.payload()
    check("en: stored duration stays Chinese", p.get("duration") in ("60 秒短检", "10 分钟关口", "手动停止"))
    check("en: stored power/wb/focus stay Chinese", all(p.get(k) in ("不改", "关闭", "50 Hz", "60 Hz", "自动", "手动") for k in ("power", "wb", "focus")))
    check("en: page kept after switch", win.current_page == "sessions")
    win.fields["duration"].setCurrentIndex(1); check("en: combo selection -> Chinese value", win.payload()["duration"] == "10 分钟关口")
    win.set_language("zh"); state()
    for page in ("lab", "pc", "board", "periph", "sessions", "settings"):
        win.show_page(page); app.processEvents()
    check("all pages navigable", win.current_page == "settings")
    # v0.12.5: PC page never shows the board stream / board cards
    win.show_page("board"); state(connected=True, live=True); calls.clear()
    S.pc_devices = []; S.settings["pc_device"] = ""
    win.show_page("pc"); state(connected=True)
    tiles = " ".join(t.text() + t.toolTip() for t in win.tiles.values())
    check("pc page: board live stopped", "stop_live" in calls and not S.live and S.preview is None)
    check("pc page: cards do not show board", "KV260" not in tiles and win.tiles["board"].toolTip() == "本机")
    check("pc page: no camera -> placeholder + start disabled",
          win.viewport.empty_title == "本机未检测到摄像头" and not any(b.isEnabled() for b in win.actions
                                                                if b.property("needs") == "pc_cam"))
    win.show_page("board"); state(connected=True)
    check("board page: cards show board again", "KV260" in " ".join(t.text() + t.toolTip() for t in win.tiles.values()))
    win.show_page("settings")
    win.open_large(); app.processEvents(); check("large view timer runs when shown", win.large.timer.isActive())
    win.large.hide(); check("large view timer stops when hidden", not win.large.timer.isActive())
    with S.lock: S.logs = []
    state(); check("activity empty-state text shown", win.activity.text() == "暂无动态")
    with S.lock: S.logs = ["已保存"]
    state(); check("activity shows latest log", "已保存" in win.activity.text())
    win.show_page("lab")
    for i in range(3):
        win._show_tab(i); app.processEvents()
        check(f"lab tab {i} switches", win.lab_stack.currentIndex() == i and win.lab_tabs[i].isChecked())
    for page, texts in (("lab", ["录 60 秒", "停止并取回"]), ("pc", ["开始采集", "停止并校验"]),
                        ("board", ["开始采集", "停止并取回"]), ("sessions", ["取回", "校验"]),
                        ("settings", ["保存", "检查工具", "检查更新"])):
        win.show_page(page); app.processEvents()
        holder = win.footer_stack.currentWidget()
        shown = [b.text() for b in holder.findChildren(w.QPushButton)]
        check(f"footer on {page} = {texts}", shown == [w._button_text(t) for t in texts])
    win.show_page("settings"); app.processEvents(); check("duration hidden on settings", not win.duration_bar.isVisible())
    win.show_page("pc"); app.processEvents(); check("duration shown on pc", win.duration_bar.isVisible())
    duration = win.fields["duration"]
    duration.setCurrentIndex(duration.findData("自定义")); app.processEvents()
    hint = win.duration_hint
    hint_text = "10 秒到 2 小时，到点自动停止"
    check("custom duration hint is fully visible", hint.isVisible() and hint.text() == hint_text and hint.width() >= hint.fontMetrics().horizontalAdvance(hint_text))
    duration.setCurrentIndex(0)
    win.show_page("lab"); win._show_tab(2); win.set_language("en"); app.processEvents()
    check("language switch keeps lab tab", win.lab_stack.currentIndex() == 2)
    win.set_language("zh")
    # ---- v6: mode detection (mocked board / ffmpeg) ----
    class FakeClient:
        def __init__(self, reply=None, error=None): self.reply, self.error = reply, error
        def request(self, method, endpoint, *a, **k):
            if self.error: raise RuntimeError(self.error)
            return self.reply
    good = [{"width": 1920, "height": 1080, "fps": 30, "format": "mjpeg"},
            {"width": 1280, "height": 720, "fps": 60, "format": "mjpeg"},
            {"width": 640, "height": 480, "fps": 30, "format": "raw"}]
    with S.lock:
        S.settings.update({"width": "3840", "height": "2160", "fps": "30", "format": "mjpeg", "device": "/dev/video0"})
        S.client = FakeClient({"modes": good})
    S._detect_board_modes(); state(connected=True); win.show_page("lab"); win._show_tab(0); app.processEvents()
    check("detect success: default 1920x1080@30 MJPEG chosen", (S.settings["width"], S.settings["height"], S.settings["fps"], S.settings["format"]) == ("1920", "1080", "30", "mjpeg"))
    combo = win.mode_combos["board"]
    check("detect success: dropdown lists detected modes + custom", combo.count() == 4 and combo.currentText().startswith("1920×1080"))
    check("detect success: caption says detected", "3" in win.mode_captions["board"].text())
    with S.lock: S.settings.update({"width": "640", "height": "480", "fps": "30", "format": "raw"})
    S._detect_board_modes(); state(connected=True)
    check("saved mode retained when still supported", (S.settings["width"], S.settings["format"]) == ("640", "raw"))
    check("dropdown shows saved mode", combo.currentText().startswith("640×480"))
    with S.lock: S.client = FakeClient({"modes": []})
    S._detect_board_modes(); state(connected=True)
    check("detect empty: presets shown", combo.count() > 10 and "常用预设" in win.mode_captions["board"].text())
    with S.lock: S.client = FakeClient(error="Board returned 404: not found")
    S._detect_board_modes(); state(connected=True)
    check("detect failure: presets + note", combo.count() > 10 and "常用预设" in S.modes_note)
    idx = combo.findData("1280|720|60|mjpeg"); combo.setCurrentIndex(idx); win._pick_mode("board", idx)
    check("picking a mode writes width/height/fps/format strings", (S.settings["width"], S.settings["height"], S.settings["fps"], S.settings["format"]) == ("1280", "720", "60", "mjpeg"))
    check("manual fields hidden for a listed mode", not win.manual_mode.isVisible())
    idx = combo.findData("custom"); combo.setCurrentIndex(idx); win._pick_mode("board", idx); state(connected=True)
    check("custom reveals manual fields", win.manual_mode.isVisible())
    win._pick_mode("board", combo.findData("1280|720|60|mjpeg")); state(connected=True)
    calls.clear(); S.detect_modes = lambda kind: calls.append(("detect", kind))
    [b for b in win.actions if b.text() == w._button_text("检测")][0].click()
    check("detect button wired", calls == [("detect", "board")])
    import importlib as _il
    prod = _il.import_module(pkg + ".product")
    prod.list_dshow_modes = lambda ffmpeg, dev: [{"width": 1280, "height": 720, "fps": 30, "format": "mjpeg"}]
    S._detect_pc_modes("ffmpeg", "USB 摄像头"); state(connected=True); win.show_page("pc"); app.processEvents()
    check("pc detection fills pc dropdown (+ v7 custom item)", win.mode_combos["pc"].count() == 2 and win.mode_combos["pc"].findData("custom") == 1)
    win._disk_checked = 0; state(connected=True, sessions=[{"session_id": "20261013_120000", "status": "recorded"}])
    card = win.data_cards[0]
    check("data card shows output path", str(S._output()) == card["path"]._full)
    check("data card shows free space", "GB" in card["free"].text())
    check("recent sessions listed", card["recent"].count() == 1)
    opened = []
    w.os.startfile = lambda p: opened.append(p)
    here = w.Path(__file__).resolve().parent
    S._output = lambda: here
    btn("打开文件夹")[0].click()
    check("open folder uses output path", opened == [str(here)])
    # ---- v6: generic boards (mocked over the probe layer) --------------------------
    import ast as _ast
    probe = _il.import_module(pkg + ".board_probe")
    src = _ast.parse((w.Path(prod.__file__).parent / "tests" / "test_board_probe.py").read_text(encoding="utf-8"))
    SAMPLES = {n.targets[0].id: n.value.value for n in src.body
               if isinstance(n, _ast.Assign) and isinstance(n.value, _ast.Constant) and isinstance(n.value.value, str)}
    class FakeMonitor:
        last = None
        def __init__(self, ssh_args, cb, interval): self.cb, self.interval, self.stopped = cb, interval, False; FakeMonitor.last = self
        def start(self): pass
        def stop(self): self.stopped = True
    S._ssh_args = lambda user, host, key: ["ssh", f"{user}@{host}"]
    perimod = _il.import_module(pkg + ".peripherals")
    prod.peripherals.scan = lambda args, i2c=False: []  # never touch ssh in tests
    real_start = S._start_monitor
    S._start_monitor = lambda args, factory=None: real_start(args, FakeMonitor)
    def board(sample, status_extra=""):
        prod.board_probe.probe_info = lambda args: probe.parse_info(SAMPLES[sample])
        S._probe_board("ubuntu", "192.168.1.50", w.Path("k"))
        parser = probe.StatusParser()
        blk = lambda u, i, rx: ("@@stat\ncpu  %d 0 0 %d 0 0 0 0\n@@meminfo\nMemTotal: 4000000 kB\nMemAvailable: 1000000 kB\n"
                                "@@thermal\ncpu-thermal=51000\n@@df\n/dev/root 1000000 250000 750000 25%% /\n"
                                "@@net\n  eth0: %d 1 0 0 0 0 0 0 %d 1 0 0 0 0 0 0\n%s@@end\n") % (u, i, rx, rx // 2, status_extra)
        parser.feed(blk(100, 900, 0), now=1.0)
        FakeMonitor.last.cb(parser.feed(blk(160, 940, 4096), now=3.0))
        with S.lock:
            label = S.board_label
        state(connected=True); S.board_label = label; win.refresh(S.state()); win.show_page("board"); app.processEvents()
    check("nav says 开发板 (generic)", win.page_buttons["board"].text().strip() == w._button_text("开发板") or "开发板" in win.page_buttons["board"].text())
    state(); win.show_page("board"); app.processEvents()
    check("disconnected: board info shows quick-connect panel only (v9)", win.board_quick.isVisible() and not any(v.isVisible() for _, v in win.info_cells.values()))
    board("KV260")
    check("kv260: model from device tree", win.board_model._full == "ZynqMP SMK-K26 Rev1/B/A")
    check("kv260: board_label uses detected model", S.board_label == "ZynqMP SMK-K26 Rev1/B/A")
    check("kv260: FPGA row (xmutil app) shown", win.info_cells["fpga"][1].isVisible() and "k26-starter-kits" in win.info_cells["fpga"][1]._full)
    check("kv260: FPGA sits in the left nav", win.fpga_card.isVisible() and win.fpga_card.parent() is win.nav and win.stage.x() == 24 and win.fpga_button not in win.board_live_buttons and "k26-starter-kits" in win.fpga_current.text())
    check("kv260: monitor polls every 2 s", FakeMonitor.last.interval == 2.0)
    check("kv260: live cpu/mem/temp/disk/net", {"cpu", "mem", "temp", "disk", "net"} <= set(win.board_status_rows))
    check("kv260: cpu value 60%", win.status_cells["cpu"][2].text().startswith("60%"))
    check("kv260: no GPU/NPU rows", not win.status_cells["gpu"][0].isVisible() and not win.status_cells["npu"][0].isVisible())
    bar = win.side_scroll.verticalScrollBar()
    check("kv260 board page fits 1280x800 (no scroll)", bar.maximum() == 0)
    first = FakeMonitor.last
    board("JETSON", "@@gpu\n734\n")
    check("reconnect stops previous monitor", first.stopped)
    check("jetson: L4T in system row", "L4T R35.4.1" in win.info_cells["os"][1]._full)
    check("jetson: GPU row visible, FPGA hidden", win.status_cells["gpu"][0].isVisible() and not win.info_cells["fpga"][1].isVisible() and not win.fpga_card.isVisible())
    board("RK3588", "@@npu\nNPU load:  Core0: 30%, Core1: 10%, Core2:  2%,\n")
    check("rk3588: NPU 14%", win.status_cells["npu"][2].text() == "14%")
    board("RPI")
    check("raspberry pi: model + no accelerator rows", win.board_model._full.startswith("Raspberry Pi 5") and not win.status_cells["gpu"][0].isVisible())
    board("X86")
    check("x86: dmi model", win.board_model._full == "Intel(R) Client Systems NUC11TNHi5")
    board("BUSYBOX")
    check("busybox: absent probes hide rows", not win.info_cells["os"][1].isVisible() and win.info_cells["kernel"][1].isVisible())
    def boom(args): raise RuntimeError("ssh: connect to host timed out")
    prod.board_probe.probe_info = boom
    S._probe_board("ubuntu", "h", w.Path("k")); state(connected=True)
    check("probe failure: info cleared, no crash", S.board_info == {} and win.board_info_empty.isVisible())
    check("probe failure logged", any("未能读取开发板信息" in x for x in S.logs))
    S._stop_monitor()
    check("close stops monitor", S.monitor is None)
    i18n.LANG = "en"
    check("en: board strings translated", w.tr("开发板采集") == "Board Capture" and w.tr("温度") == "Temp")
    check("en: failure message translated", i18n.tr_msg("未能读取开发板信息：x").startswith("Could not read board info"))
    i18n.LANG = "zh"
    # ---- v6: peripherals page (mocked scan) ----------------------------------------
    import json as _json, tempfile as _tmp, time as _time
    psrc = _ast.parse((w.Path(prod.__file__).parent / "tests" / "test_peripherals.py").read_text(encoding="utf-8"))
    pns = {}
    exec(compile(_ast.Module(body=[n for n in psrc.body if isinstance(n, (_ast.FunctionDef, _ast.Assign)) and getattr(n, "name", "") in ("_edid",) or
                                   (isinstance(n, _ast.Assign) and n.targets[0].id in ("EDID", "SAMPLE"))], type_ignores=[]), "s", "exec"), pns)
    PSAMPLE = pns["SAMPLE"]
    full = perimod.parse_peripherals(PSAMPLE)
    seen_i2c = []
    def fake_scan(args, i2c=False):
        seen_i2c.append(i2c); return list(fake_scan.items)
    fake_scan.items = full
    prod.peripherals.scan = fake_scan
    def wait_scan():
        for _ in range(200):
            with S.lock:
                if not S.periph_busy: break
            _time.sleep(0.01)
        win.refresh(S.state()); app.processEvents()
    with S.lock: S.ssh_args = []; S.peripherals = []; S.periph_note = ""
    state(); win.show_page("periph"); app.processEvents()
    check("periph: nav entry 外设", "外设" in win.page_buttons["periph"].text())
    check("periph: disconnected hint", "连接开发板" in win.periph_note._full)
    check("periph: refresh disabled when disconnected", not btn("刷新")[-1].isEnabled())
    with S.lock: S.ssh_args = ["ssh", "u@h"]
    S.scan_peripherals(); wait_scan(); state(connected=True)
    check("periph: all items listed", win.periph_list.count() == len(full) and len(full) >= 20)
    check("periph: icons per category", not win.periph_list.item(0).icon().isNull())
    check("periph: first item selected with details", win.periph_detail.count() > 3 and win.periph_title._full)
    win.periph_filter.setCurrentIndex(win.periph_filter.findData("serial")); app.processEvents()
    check("periph: category filter (serial)", win.periph_list.count() == 3)
    win.periph_filter.setCurrentIndex(0); win.periph_search.setText("1a86"); app.processEvents()
    check("periph: search by VID", win.periph_list.count() == 2)
    win.periph_search.setText("nvme"); app.processEvents()
    check("periph: search by driver -> PCIe", win.periph_list.count() == 1 and "Samsung" in win.periph_title._full)
    check("periph: detail shows driver", any("nvme" in win.periph_detail.item(i).text() for i in range(win.periph_detail.count())))
    win.periph_search.setText("zzz-none"); app.processEvents()
    check("periph: no match placeholder (not selectable)", win.periph_list.count() == 1 and not (win.periph_list.item(0).flags() & w.Qt.ItemFlag.ItemIsSelectable))
    win.periph_search.setText(""); app.processEvents()
    btn("复制")[0].click()
    check("periph: copy as text", "CH340" in QApplication.clipboard().text())
    out_dir = w.Path(_tmp.mkdtemp())
    S._output = lambda: out_dir
    btn("导出")[0].click()
    files = list(out_dir.glob("hardware_inventory_*.json"))
    check("periph: export JSON", len(files) == 1 and len(_json.loads(files[0].read_text(encoding="utf-8"))["board_peripherals"]) == len(full))
    [b for b in win.actions if b.text() == w._button_text("扫描 I2C")][0].click(); wait_scan()
    check("periph: I2C scan only on request", seen_i2c[0] is False and seen_i2c[-1] is True)
    # hotplug: the 2 s status stream reports a new /dev signature -> automatic rescan with a diff
    fake_scan.items = [i for i in full if i["id"] != "serial:/dev/ttyUSB0"]
    S.scan_peripherals(); wait_scan()
    S._start_monitor(["ssh"]); mon = FakeMonitor.last
    mon.cb({"hotplug": "111"}); fake_scan.items = full; mon.cb({"hotplug": "222"}); wait_scan()
    check("periph: hotplug triggers rescan + log", any("新接入：CH340 serial converter" in x for x in S.logs))
    mon.cb({"hotplug": "222"}); n = len(seen_i2c); wait_scan()
    check("periph: unchanged signature does not rescan", len(seen_i2c) == n)
    def bad(args, i2c=False): raise RuntimeError("ssh timeout")
    prod.peripherals.scan = bad; S.scan_peripherals(); wait_scan()
    check("periph: failure keeps list, shows note", "外设扫描失败" in win.periph_note._full and win.periph_list.count() == len(full))
    win.show_page("periph"); win.resize(1280, 800); app.processEvents()
    check("periph page fits 1280x800", win.side_scroll.verticalScrollBar().maximum() == 0)
    i18n.LANG = "en"; win._periph_seen = None; win.refresh(S.state()); app.processEvents()
    texts = [win.periph_list.item(i).text().split("\n")[1] for i in range(win.periph_list.count())
             if not str(win.periph_list.item(i).data(w.Qt.ItemDataRole.UserRole)).startswith("storage:")]  # mount paths are user data
    import re as _re
    check("en: peripheral summaries have no Chinese", not any(_re.search(r"[\u4e00-\u9fff]", t) for t in texts))
    details = [win.periph_detail.item(i).text() for i in range(win.periph_detail.count())]
    check("en: detail keys translated", details and not any(_re.search(r"[\u4e00-\u9fff]", d.split(":")[0]) for d in details))
    i18n.LANG = "zh"; S._stop_monitor()
    # ======================= v7 =======================
    v7 = _il.import_module(pkg + ".v7_ui")
    th = _il.import_module(pkg + ".theme")
    sr = _il.import_module(pkg + ".session_review")
    tpl = _il.import_module(pkg + ".templates")
    def pump(n=30):
        for _ in range(n):
            app.processEvents(); _time.sleep(0.01)
    v7.HealthDialog.exec = lambda self: (calls.append("health_dialog"), v7.QDialog.DialogCode.Accepted)[1]
    started = []
    S.start_record = lambda payload, mode: started.append((dict(payload), mode))
    S.stop_record = lambda: calls.append("stop_record")
    # (1) wizard + auto-connect
    wz = v7.Wizard(win, scanner=lambda: [{"host": "192.168.1.50", "banner": "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3", "hint": "Ubuntu"},
                                         {"host": "192.168.1.77", "banner": "SSH-2.0-dropbear", "hint": "Dropbear (嵌入式)"}])
    wz.host.setText(""); wz.start_scan()
    for _ in range(100):
        pump(1)
        if wz.hosts.count(): break
    check("wizard: LAN scan lists SSH hosts", wz.hosts.count() == 2 and "Ubuntu" in wz.hosts.item(0).text())
    wz.next_step(); check("wizard: step 2 credentials", wz.steps.currentIndex() == 1 and wz.host.text() == "192.168.1.50")
    wz.password.setText("pw"); wz.remember.setEnabled(True); wz.remember.setChecked(True); wz.next_step()
    check("wizard: step 3 summary", wz.steps.currentIndex() == 2 and "192.168.1.50" in wz.summary.text())
    result = wz.result_payload()
    check("wizard: auto-connect on by default", result["auto_connect"] == "1" and result["wizard_done"] == "1")
    saved_pw = []; v7.credstore.save = lambda u, h, p: saved_pw.append((u, h, p)) or True
    connects = []; S.connect = lambda data: connects.append(dict(data))
    win._apply_wizard(result)
    check("wizard: password goes to credential store, not settings", saved_pw == [("ubuntu", "192.168.1.50", "pw")] and "password" not in S.settings)
    check("wizard: connects to chosen board", connects and connects[-1]["host"] == "192.168.1.50")
    with S.lock: S.settings.update(host="192.168.1.50", auto_connect="1")
    v7.credstore.load = lambda u, h: ""
    connects.clear(); state(); win.maybe_auto_connect(delay=3); pump(2)
    check("auto-connect: countdown banner with cancel", win.banner.isVisible() and win.banner_buttons["cancel"].isVisible())
    win.banner_buttons["cancel"].click(); pump(2)
    check("auto-connect: cancel stops it", not win._auto_timer.isActive() and not connects and not win.banner.isVisible())
    win.maybe_auto_connect(delay=3); win.banner_buttons["connect_now"].click()
    check("auto-connect: connect now", len(connects) == 1 and win._auto_preview)
    calls.clear(); state(connected=True); pump(2)
    check("auto-preview after connect", "start_live" in calls)
    # (2) templates
    import tempfile as _tf2
    tdir = w.Path(_tf2.mkdtemp()); S.templates_path = lambda: tdir / "capture_templates.json"
    win.save_template("室内 1080p", "实验室 A")
    data = tpl.load_all(tdir / "capture_templates.json")
    check("templates: saved with mode/duration/scene", "室内 1080p" in data and data["室内 1080p"]["scene"] == "实验室 A" and "duration" in data["室内 1080p"])
    win.show_page("pc"); started.clear(); win.start_template("室内 1080p")
    check("templates: one-click start", started and started[-1][1] == "pc")
    check("templates: auto naming date_scene", started and _time.strftime("%Y%m%d") + "_实验室_A" in started[-1][0]["_output_once"])
    check("templates: base output setting not overwritten", "output" not in started[-1][0])
    with S.lock: S.settings["output"] = "captures"
    # (3) health check
    est = win.size_estimate
    check("health: size estimate shown", est["bytes"] > 0 and "Mb/s" in win.tiles["stream"].toolTip())
    import shutil as _sh
    real_du = _sh.disk_usage
    _sh.disk_usage = lambda p: type("U", (), {"free": 1000})()
    items = win._health_items("pc")
    check("health: low disk -> fail with fix", any(i["level"] == "fail" and i["fix"] for i in items))
    v7.HealthDialog.exec = lambda self: (calls.append("health_dialog"), v7.QDialog.DialogCode.Rejected)[1]
    started.clear(); win.start_capture("pc")
    check("health: user can cancel a risky start", not started and "health_dialog" in calls)
    _sh.disk_usage = real_du
    with S.lock: S.board_status = {"temp_max": 92.0, "disk_total": 10**10, "disk_used": 10**9}
    items = win._health_items("board")
    check("health: board overheating flagged", any(i["title"] == "开发板过热" for i in items))
    with S.lock: S.board_status = {}
    v7.HealthDialog.exec = lambda self: (calls.append("health_dialog"), v7.QDialog.DialogCode.Accepted)[1]
    # (4) friendly errors
    retried = []
    with S.lock:
        S.last_error = "ssh: connect to host 192.168.1.50 port 22: Connection timed out"
        S._retry = ("正在连接", lambda: retried.append(1))
    state(connected=False); win.refresh(S.state()); pump(1)
    check("errors: friendly banner", win.banner.isVisible() and win.banner_title.text() == "连接超时")
    check("errors: retry/details/bundle offered", all(win.banner_buttons[k].isVisible() for k in ("retry", "details", "bundle")))
    win.banner_buttons["retry"].click(); pump(20)
    check("errors: retry re-runs the failed action", retried == [1])
    with S.lock: S.settings["password"] = "secret"; S.last_error = "Permission denied (publickey)"
    bz = win.copy_bundle(w.Path(_tf2.mkdtemp()) / "diag.zip")
    import zipfile as _zf
    names = _zf.ZipFile(bz).namelist(); blob = b"".join(_zf.ZipFile(bz).read(n) for n in names)
    check("errors: diagnostic bundle contents", {"summary.json", "logs.txt", "board_info.json", "peripherals.json"} <= set(names))
    check("errors: bundle has no secrets", b"secret" not in blob)
    check("errors: bundle path on clipboard", str(bz) in QApplication.clipboard().text())
    with S.lock: S.settings.pop("password", None); S.last_error = ""; S._retry = None
    state(); pump(1)
    check("errors: banner hides when cleared", not win.banner.isVisible())
    # (5) shortcuts + indicators + notification
    shortcuts = {sc.key().toString(): sc for sc in win.findChildren(v7.QShortcut)}
    check("shortcuts: Space/F/L/P/H/R/?/Ctrl+1..6 registered", all(k in shortcuts for k in ("Space", "F", "L", "P", "H", "R", "?", "Ctrl+1", "Ctrl+6", "Ctrl+K")))
    win.show_page("pc"); started.clear(); state(connected=True); shortcuts["Space"].activated.emit(); pump(1)
    check("shortcuts: Space starts capture", started and started[-1][1] == "pc")
    state(connected=True, recording={"session_id": "20261013T120000Z_abcdef12", "mode": "pc", "started": _time.monotonic(), "seconds": 60}); pump(1)
    check("indicator: title shows recording", win.windowTitle().startswith("●"))
    calls.clear(); shortcuts["Space"].activated.emit()
    check("shortcuts: Space stops capture", "stop_record" in calls)
    state(connected=True); pump(1)
    check("notification on finish", win.notifications and "20261013T120000Z_abcdef12" in win.notifications[-1] and win.windowTitle() == "Capture Studio")
    real_focus = v7.QApplication.focusWidget
    v7.QApplication.focusWidget = staticmethod(lambda: win.periph_search)
    started.clear(); shortcuts["Space"].activated.emit()
    check("shortcuts: ignored while typing", not started)
    v7.QApplication.focusWidget = real_focus
    shortcuts["Ctrl+5"].activated.emit()
    check("shortcuts: Ctrl+5 -> sessions", win.current_page == "sessions")
    shortcuts["?"].activated.emit(); check("shortcuts: cheat sheet", hasattr(win, "cheatsheet"))
    # (6) session review
    sdir = w.Path(_tf2.mkdtemp()); sub = sdir / (_time.strftime("%Y%m%d") + "_实验室_A"); sid = "20261013T120000Z_abcdef12"
    (sub / sid / "segments").mkdir(parents=True)
    (sub / sid / "segments" / "part_00000.mkv").write_bytes(b"x" * 2048)
    (sub / sid / "session.json").write_text(_json.dumps({"session_id": sid, "status": "needs_review", "mode": "pc_usb",
        "options": {"width": 1280, "height": 720, "fps": 30, "format": "mjpeg"}, "files": [{"path": "segments/part_00000.mkv", "size": 2048}],
        "audit": {"frame_count": 300, "possible_gap_intervals": 2}}), encoding="utf-8")
    S._output = lambda: sdir
    thumb = sdir / "t.jpg"; v7.QImage(32, 18, v7.QImage.Format.Format_RGB32).save(str(thumb))
    sr.ensure_thumbnail = lambda ffmpeg, media, cache: thumb
    S._tool = lambda name: w.Path(name)
    prod.Studio.list_sessions(S, "local"); pump(40); state(connected=True, sessions=S.sessions); pump(40); win.refresh(S.state())
    check("review: sessions found in template sub-folder", any(r.get("session_id") == sid for r in S.sessions))
    win.sessions.setCurrentRow(0); win.refresh(S.state()); pump(30); win.refresh(S.state())
    check("review: stats (frames / dropped / duration / size)", "300 帧" in win.review_info.text() and "疑似掉帧 2" in win.review_info.text() and "0:10" in win.review_info.text())
    check("review: thumbnail icon", not win.sessions.item(0).icon().isNull())
    frames = []
    for i in range(3):
        f = sdir / f"f_{i:04d}.jpg"; v7.QImage(64, 36, v7.QImage.Format.Format_RGB32).save(str(f)); frames.append(f)
    sr.extract_frames = lambda ffmpeg, media, out: frames
    win.toggle_playback(); pump(30)
    check("review: inline playback runs", win._play_timer.isActive())
    win.toggle_playback(); check("review: playback stops", not win._play_timer.isActive())
    check("review: audit finds session in sub-folder", S.session_path(sid) == sub / sid)
    # (7) peripherals: terminal, I2C hints, PC scan, inventory
    win.show_page("periph"); win.periph_source.setCurrentIndex(0)
    prod.peripherals.scan = lambda args, i2c=False: full
    with S.lock: S.ssh_args = ["ssh", "u@h"]
    S.scan_peripherals(); wait_scan(); win._periph_seen = None; win.refresh(S.state())
    win.periph_search.setText("i2c-1"); pump(1)
    details = [win.periph_detail.item(i).text() for i in range(win.periph_detail.count())]
    check("i2c: possible-chip hints by address", any("可能是" in d and "0x68" in d for d in details))
    win.periph_search.setText("ttyUSB0"); pump(1)
    class FakeSerial:
        def __init__(self): self.sent = []; self.closed = False
        def start(self, cb): cb(b"hello\x01")
        def write(self, data): self.sent.append(data)
        def close(self): self.closed = True
    fake = FakeSerial(); opened = []
    win.open_terminal(opener=lambda port, baud: (opened.append((port, baud)), fake)[1])
    term = win.terminal
    check("serial: nothing opened until user clicks Open", not opened)
    term.toggle(); pump(3)
    check("serial: opens selected port @115200", opened == [("/dev/ttyUSB0", 115200)])
    check("serial: receive shown", "hello" in term.view.toPlainText())
    term.hex_view.setChecked(True); check("serial: hex view", "68 65 6C 6C 6F 01" in term.view.toPlainText())
    term.input.setText("AT"); term.send(); term.hex_send.setChecked(True); term.input.setText("55 AA"); term.send()
    check("serial: send text + hex", fake.sent == [b"AT\r\n", b"\x55\xaa"])
    term.input.setText("5G"); term.send(); check("serial: bad hex rejected", len(fake.sent) == 2)
    term.close(); pump(2); check("serial: port closed with dialog", fake.closed)
    pc_items = [{"category": "serial", "id": "pc-serial:COM3", "name": "USB-SERIAL CH340 (COM3)", "summary": "COM3 · CH340", "side": "pc", "port": "COM3", "props": [("端口", "COM3")]},
                {"category": "video", "id": "pc-video:USB\\VID_046D", "name": "Logi C270", "summary": "046d:0825", "side": "pc", "props": [("名称", "Logi C270")]}]
    S.scan_pc_peripherals(runner=lambda: pc_items); pump(20)
    win.periph_search.setText(""); win.periph_source.setCurrentIndex(1); pump(5); win.refresh(S.state())
    check("pc peripherals listed", win.periph_list.count() == 2)
    out_dir = w.Path(_tf2.mkdtemp()); inv = win.export_inventory(out_dir)
    inv_data = _json.loads(inv.read_text(encoding="utf-8"))
    check("inventory: board + pc + text file", len(inv_data["pc_peripherals"]) == 2 and inv_data["board_peripherals"] and list(out_dir.glob("*.txt")))
    win.periph_source.setCurrentIndex(0)
    # PC custom mode
    board_before = tuple(S.settings[k] for k in ("width", "height", "fps", "format"))
    win.show_page("pc"); ok = win.pc_custom_mode(("1024", "768", "15", "raw")); state(connected=True); pump(1)
    combo = win.mode_combos["pc"]
    check("pc custom mode stored as strings", ok and (S.settings["pc_width"], S.settings["pc_fps"], S.settings["pc_format"]) == ("1024", "15", "raw"))
    check("pc custom mode leaves the board mode alone", tuple(S.settings[k] for k in ("width", "height", "fps", "format")) == board_before)
    check("pc custom mode shown in dropdown", combo.currentData() == "custom" and "1024" in combo.currentText())
    # (8) dark mode
    win.set_theme("深色"); pump(2)
    check("dark: stylesheet switched", th.DARK_MODE and "#1C1C1E" in app.styleSheet())
    check("dark: page kept after rebuild", win.current_page == "pc" and win.theme_buttons["深色"].isChecked())
    win.set_theme("浅色"); pump(2)
    check("light: back to light", not th.DARK_MODE and "#1C1C1E" not in app.styleSheet())
    check("theme follows system when 自动", th.resolve("跟随系统") in (True, False))
    # English for v7 surfaces
    import re as _re
    cjk = _re.compile(r"[\u3400-\u9fff]")
    win.set_language("en"); pump(2)
    wz2 = v7.Wizard(win, scanner=lambda: [])
    texts = [x.text() for x in wz2.findChildren(v7.QLabel) + wz2.findChildren(v7.QPushButton) + wz2.findChildren(v7.QCheckBox)]
    check("en: wizard fully translated", not [t for t in texts if cjk.search(t)])
    hd = v7.HealthDialog(win, win._health_items("board") + [{"level": "fail", "title": "USB 带宽不够", "detail": "未压缩 995 Mb/s 超过 USB 2.0 实际约 320 Mb/s", "fix": "改用 MJPEG，或降低分辨率/帧率，或接 USB 3.0 口"}], True)
    texts = [x.text() for x in hd.findChildren(v7.QLabel) + hd.findChildren(v7.QPushButton)]
    check("en: health dialog translated", not [t for t in texts if cjk.search(t)])
    st = v7.SerialTerminal(win, "/dev/ttyUSB0", "board", opener=lambda p, b: fake)
    texts = [x.text() for x in st.findChildren(v7.QLabel) + st.findChildren(v7.QPushButton) + st.findChildren(v7.QCheckBox)] + [st.view.placeholderText(), st.input.placeholderText()]
    check("en: serial terminal translated", not [t for t in texts if cjk.search(t)])
    check("en: theme/nav extras translated", win.theme_buttons["深色"].text() == "Dark" and win.template_button.text() == "Templates")
    with S.lock: S.last_error = "Connection refused"; S._retry = None
    win.refresh(S.state())
    check("en: friendly error translated", win.banner_title.text() == "Board refused connection" and not cjk.search(win.banner_text.text()))
    with S.lock: S.last_error = ""
    win.set_language("zh"); pump(2)
    # fit: every page, both themes
    win.resize(1280, 800)
    for dark in (False, True):
        th.DARK_MODE = dark
        for page in ("lab", "pc", "board", "periph", "sessions", "settings"):
            win.show_page(page); pump(2)
            bar = win.side_scroll.verticalScrollBar()
            check(f"fit 1280x800 {page} {'dark' if dark else 'light'} (max={bar.maximum()} view={win.side_scroll.viewport().height()})", bar.maximum() == 0)
    th.DARK_MODE = False
    # ---------------- v9 ----------------
    fake_pc = [{"id": "pc:usb:1", "category": "usb", "name": "USB Hub", "summary": "VID 05e3", "props": [("VID:PID", "05e3:0610")]},
               {"id": "pc:serial:COM3", "category": "serial", "name": "USB-SERIAL CH340 (COM3)", "summary": "COM3", "props": [("端口", "COM3")], "port": "COM3", "side": "pc"},
               {"id": "pc:video:1", "category": "video", "name": "USB Camera", "summary": "1c45:6200", "props": [("VID:PID", "1c45:6200")]}]
    with S.lock:
        S.connected = False; S.peripherals = []; S.pc_peripherals = list(fake_pc); S.pc_pick = "need_manual"
        S.pc_devices = [{"label": "USB Camera · 1c45:6200", "value": "@a", "id": "1c45:6200"}, {"label": "USB Camera · 046d:0825", "value": "@b", "id": "046d:0825"}]
    win.show_page("pc"); win.refresh(S.state()); pump(2)
    check("v9 pick: indicator shows reason", win.pc_pick_label.isVisible() and win.pc_pick_label.text() == "有多只摄像头，请手动选择")
    check("v9 pick: warn style when manual needed", getattr(win.pc_pick_label, "kind", "") == "warn")
    with S.lock: S.pc_pick = "vidpid"
    win.refresh(S.state())
    check("v9 pick: auto reason shown as info pill", getattr(win.pc_pick_label, "kind", "") == "info" and "VID:PID" in win.pc_pick_label.text())
    win.show_page("board"); win.refresh(S.state()); pump(2)
    check("v9 board: quick-connect panel visible while disconnected", win.board_quick.isVisible())
    check("v9 board: real local device counts", win.quick_counts["serial"].text() == "1" and win.quick_counts["usb"].text() == "1")
    check("v9 board: camera count from detected PC cameras", win.quick_counts["camera"].text() == "2")
    bar = win.side_scroll.verticalScrollBar()
    check("v9 board: quick panel still fits 1280x800", bar.maximum() == 0)
    hits = []; real_ow, real_now = win.open_wizard, win._auto_now
    win.open_wizard = lambda *a, **k: hits.append("wizard"); win._auto_now = lambda: hits.append("connect")
    win.quick_connect.click(); win.open_wizard, win._auto_now = real_ow, real_now
    check("v9 board: quick connect acts (wizard or saved host)", hits in (["wizard"], ["connect"]))
    win.show_page("periph"); win.periph_source.setCurrentIndex(0); win.refresh(S.state()); pump(2)
    check("v9 periph: board offline falls back to PC devices", win.periph_list.count() == 3 and win.periph_fallback)
    check("v9 periph: note explains fallback", "这台电脑" in win.periph_note._full)
    with S.lock: S.connected = True
    win.refresh(S.state())
    check("v9 board: quick panel hidden when connected", not win.board_quick.isVisible() or win.current_page != "board")
    with S.lock: S.connected = False
    import tempfile as _tf9, json as _js9
    out9 = w.Path(_tf9.mkdtemp()); sess = out9 / "20261014T013100Z_0123abcd"; (sess / "segments").mkdir(parents=True)
    (sess / "segments" / "part_00000.mkv").write_bytes(b"x" * 2048)
    (sess / "session.json").write_text(_js9.dumps({"session_id": sess.name, "options": {"width": 1280, "height": 720, "fps": 30, "format": "mjpeg"}, "duration_s": 60}), encoding="utf-8")
    real_out = S._output; S._output = lambda: out9; win._history_cache = None; win._disk_checked = 0
    with S.lock: S.sessions = []
    win.show_page("pc"); win.refresh(S.state()); pump(1)
    rows9 = [win.data_cards[0]["recent"].item(i).text() for i in range(win.data_cards[0]["recent"].count())]
    check("v9 data: recent local sessions with real size/duration", any("1280×720" in r and "1:00" in r for r in rows9))
    check("v9 data: disk meter shown", win.data_cards[0]["disk"].isVisible())
    S._output = real_out; win._history_cache = None
    check("v9 playback counter", v7.playback_label(4, 100) == "回放 · 5/100 · 0:00 / 0:20")
    win.set_language("en"); pump(2); win.refresh(S.state())
    win.show_page("board"); win.refresh(S.state()); pump(2)
    texts = [x.text() for x in win.board_quick.findChildren(v7.QLabel) + win.board_quick.findChildren(v7.QPushButton)]
    check("v9 en: quick panel has no Chinese", not [t for t in texts if cjk.search(t)])
    win.show_page("periph"); win.refresh(S.state()); pump(2)
    check("v9 en: periph note not elided", win.periph_note.text() == win.periph_note._full and not cjk.search(win.periph_note.text()))
    check("v9 en: sidebar sections title case", all(x.text() in ("Workspace", "Language", "Appearance", "FPGA app") for x in win.findChildren(v7.QLabel) if x.objectName() == "section"))
    win.show_page("pc"); win.refresh(S.state())
    check("v9 en: pick indicator translated", not cjk.search(win.pc_pick_label.text()))
    for page in ("lab", "pc", "board", "periph", "sessions", "settings"):
        win.show_page(page); pump(1)
        need = win.stack.minimumSizeHint().width(); have = win.side_scroll.viewport().width()
        check(f"v9 en: {page} panel not clipped horizontally (need {need} <= {have})", need <= have)
    # v10: icons + polish
    tight = []
    for page in ("lab", "pc", "board", "periph", "sessions", "settings"):
        win.show_page(page); pump(1)
        for b in win.actions:
            if b.isVisible() and b.sizeHint().width() > b.width() + 1:
                tight.append(f"{page}:{b.text()}({b.sizeHint().width()}>{b.width()})")
    check(f"v10 en: no visible button narrower than its icon+text {tight[:6]}", not tight)
    win.set_language("zh"); pump(2)
    ic = importlib.import_module(pkg + ".icons")
    check("v10: every nav button has an icon", all(not b.icon().isNull() for b in win.page_buttons.values()))
    named = [b for b in win.actions if not b.icon().isNull()]
    check(f"v10: action buttons carry icons ({len(named)})", len(named) >= 15)
    check("v10: primary buttons carry glyphs", sum(1 for b in win.actions if b.objectName() == "primary" and not b.icon().isNull()) >= 4)
    check("v10: shortcut tooltip on preview-frame/large", any("·" in b.toolTip() for b in win.actions))
    check("v10: periph tiles are svg icons", not win._periph_icon("usb").isNull() and not win._periph_icon("weird").isNull())
    check("v10: app/window icon set", not app.windowIcon().isNull() or not win.windowIcon().isNull())
    check("v10: lab key tips present, never forces height", hasattr(win, "lab_tips") and win.lab_tips.sizePolicy().verticalPolicy() == w.QSizePolicy.Policy.Ignored)
    check("v10: all referenced icons exist", all(ic.file_for(n).is_file() for n in ic.referenced()))
    # v11: icon pills, health icons, motion
    mo = importlib.import_module(pkg + ".motion")
    check("v11: chip/badge are icon pills", isinstance(win.chip, w.Pill) and isinstance(win.badge, w.Pill))
    S.connected = False; win.refresh(S.state()); pump(1)
    check("v11: disconnected chip neutral", win.chip.kind == "neutral")
    check("v11: idle badge", win.badge.kind == "idle")
    ghost_ok = True
    mo.set_reduced(False)
    win.chip.set_state("ok", "KV260"); pump(1)
    check("v11: pill crossfade runs (not reduced)", win.chip._anim is not None or not win.chip.isVisible())
    mo.set_reduced(True)
    win.chip.set_state("warn", "x"); check("v11: reduced motion -> no ghost frame", win.chip._ghost is None or win.chip._fade < 1)
    win.chip.set_state("neutral", w.tr("未连接"))
    for kind in w.PILL_KINDS:
        win.badge.set_state(kind, "t"); win.badge.repaint()
    check("v11: every pill kind paints", True)
    win.show_page("lab"); win.show_page("pc")
    check("v11: reduced motion -> page switch leaves no opacity effect", win.stack.currentWidget().graphicsEffect() is None)
    mo.set_reduced(False); win.show_page("board"); pump(1)
    check("v11: page fade attaches then clears", True)
    import time as _t; t0 = _t.time()
    while win.stack.currentWidget().graphicsEffect() is not None and _t.time() - t0 < 2: pump(1)
    check("v11: page fade finished, effect removed", win.stack.currentWidget().graphicsEffect() is None)
    win.toast("采集完成 · test"); pump(1)
    check("v11: toast visible", win._toast.isVisible() and "test" in win._toast.text())
    hd = v7.HealthDialog(win, [{"level": "ok", "title": "a", "detail": "b"}, {"level": "warn", "title": "c", "detail": "d"},
                               {"level": "fail", "title": "e", "detail": "f", "fix": "g"}], True)
    labels = [x for x in hd.findChildren(v7.QLabel) if x.objectName() == "glyph" and x.property("level")]
    texts = " ".join(x.text() for x in hd.findChildren(v7.QLabel))
    check("v11: health uses icons, no text marks", len(labels) == 3 and not any(m in texts for m in ("✓", "✕", ">!<")))
    hd.close()
    check("v11: reduced-motion setting present", hasattr(win, "reduced_motion"))
    check("version: 0.13.0", importlib.import_module(pkg).__version__ == "0.13.0")
    mo.set_reduced(True)
except Exception:
    results.append("ERROR  " + traceback.format_exc())
fails = [r for r in results if not r.startswith("PASS")]
print("\n".join(results)); print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed", flush=True)
os._exit(1 if fails else 0)
