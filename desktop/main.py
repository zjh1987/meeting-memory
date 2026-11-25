"""会议记忆 Windows 录音端：登录、录音、自动上传与纪要生成跟踪。"""

import json
import logging
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox
from urllib.parse import urlsplit

import customtkinter as ctk
from PIL import Image

from api import ApiClient, ApiError
from config import (AppConfig, clear_session, load_config, load_session,
                    logs_dir, recordings_dir, save_config, save_session)
from recorder import (RecorderError, WavRecorder, default_device_key,
                      list_input_devices, repair_wav)

APP_TITLE = "会议记忆录音端"
BG = "#F2F2F7"
CARD = "#FFFFFF"
INPUT_BG = "#F2F2F7"
TEXT = "#1C1C1E"
MUTED = "#8E8E93"
BLUE = "#007AFF"
BLUE_HOVER = "#0066D6"
DANGER = "#FF3B30"
DANGER_HOVER = "#D92D22"
GREEN = "#34C759"
ORANGE = "#FF9500"
SEPARATOR = "#E5E5EA"
KEY_COLOR = "#FF00FF"

FAMILY = "Microsoft YaHei UI"
STATUS_TEXT = {
    "uploading": "接收中",
    "pending": "排队中",
    "transcribing": "转写中",
    "minuting": "生成纪要中",
    "relating": "关联中",
    "done": "已完成",
    "failed": "处理失败",
}
FAILURE_HINTS = {
    "audio_too_long": "录音超过服务器允许的最长时长，请缩短单次录音或联系管理员调整。",
    "file_missing": "服务器上找不到音频文件，请联系管理员重新上传。",
    "asr_unavailable": "语音识别失败，录音已保留在服务器，请联系管理员处理。",
    "llm_bad_json": "纪要生成结果格式异常，请联系管理员重新生成。",
    "relation_failed": "纪要已生成，但关联归档失败，可联系管理员查看。",
}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def setup_logging() -> None:
    handler = RotatingFileHandler(
        logs_dir() / "recorder.log", maxBytes=1024 * 1024, backupCount=3,
        encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


class MiniRecorder:
    """最小化后的半透明圆形悬浮窗，显示时长和暂停/结束按钮。"""

    SIZE = 116

    def __init__(self, app: "RecorderApp"):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.9)
        self.window.configure(bg=KEY_COLOR)
        try:
            self.window.attributes("-transparentcolor", KEY_COLOR)
        except tk.TclError:
            pass
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        x = max(12, screen_w - self.SIZE - 36)
        y = max(12, screen_h - self.SIZE - 96)
        self.window.geometry(f"{self.SIZE}x{self.SIZE}+{x}+{y}")

        self.canvas = tk.Canvas(self.window, width=self.SIZE,
                                height=self.SIZE, bg=KEY_COLOR,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        center = self.SIZE // 2
        self.ring = self.canvas.create_oval(
            3, 3, self.SIZE - 3, self.SIZE - 3, fill="#1C1C1E",
            outline="#3A3A3C", width=2, tags=("drag",))
        self.timer = self.canvas.create_text(
            center, 42, text="00:00", fill="#FFFFFF",
            font=("Segoe UI", 17, "bold"), tags=("drag", "timer"))
        self.state_text = self.canvas.create_text(
            center, 62, text="录音中", fill="#AEAEB2",
            font=(FAMILY, 8), tags=("drag",))
        pause_x, y = 37, 88
        self.pause_bg = self.canvas.create_oval(
            pause_x - 12, y - 12, pause_x + 12, y + 12,
            fill="#2C2C2E", outline="", tags=("pause",))
        self.pause_icon = self.canvas.create_text(
            pause_x, y, text="Ⅱ", fill="#FFFFFF",
            font=("Segoe UI Symbol", 10), tags=("pause",))
        stop_x = 79
        self.stop_bg = self.canvas.create_oval(
            stop_x - 12, y - 12, stop_x + 12, y + 12,
            fill="#3A3A3C", outline="", tags=("stop",))
        self.canvas.create_rectangle(
            stop_x - 4, y - 4, stop_x + 4, y + 4,
            fill="#FF453A", outline="", tags=("stop",))

        self.canvas.tag_bind("pause", "<Button-1>",
                             lambda event: self._toggle_pause())
        self.canvas.tag_bind("stop", "<Button-1>",
                             lambda event: self._stop())
        self.canvas.tag_bind("timer", "<Double-Button-1>",
                             lambda event: self.app.restore_from_mini())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.visible = False
        self._drag_offset = (0, 0)
        self._tick()

    def show(self) -> None:
        self.visible = True
        self.window.deiconify()
        self.window.lift()
        self._update()

    def close(self) -> None:
        self.visible = False
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def _press(self, event) -> None:
        self._drag_offset = (0, 0)
        current = self.canvas.find_withtag("current")
        tags = self.canvas.gettags(current[0]) if current else ()
        if "pause" in tags or "stop" in tags:
            return
        self._drag_offset = (event.x_root - self.window.winfo_x(),
                             event.y_root - self.window.winfo_y())

    def _drag(self, event) -> None:
        if self._drag_offset == (0, 0):
            return
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.window.geometry(f"+{x}+{y}")

    def _toggle_pause(self) -> None:
        self.app.toggle_pause()
        self._update()

    def _stop(self) -> None:
        self.app.stop_and_upload()

    def _tick(self) -> None:
        try:
            if not self.window.winfo_exists():
                return
        except tk.TclError:
            return
        self._update()
        self.window.after(250, self._tick)

    def _update(self) -> None:
        seconds = int(self.app.recorder.elapsed())
        if seconds >= 3600:
            text = f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        else:
            text = f"{seconds // 60:02d}:{seconds % 60:02d}"
        paused = self.app.recorder.state == "paused"
        try:
            self.canvas.itemconfigure(self.timer, text=text)
            self.canvas.itemconfigure(
                self.state_text, text="已暂停" if paused else "录音中")
            self.canvas.itemconfigure(self.pause_icon, text="▶" if paused else "Ⅱ")
            self.canvas.itemconfigure(
                self.ring, outline=ORANGE if paused else BLUE)
        except tk.TclError:
            pass


class RecorderApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.config: AppConfig = load_config()
        self.api: ApiClient | None = None
        self.logged_in = False
        self.recorder = WavRecorder()
        self.ui_queue: queue.Queue = queue.Queue()
        self.devices = []
        self.device_by_label = {}
        self.projects = []
        self.templates = []
        self.template_by_label = {}
        self.pending: dict[Path, dict] = {}
        self.upload_queue: list[Path] = []
        self.queued: set[Path] = set()
        self.uploading = False
        self.last_attempt: dict[Path, float] = {}
        self.closing = False
        self.tray = None
        self.mini: MiniRecorder | None = None
        self._tray_notified = False

        self.root.title(APP_TITLE)
        self.root.configure(fg_color=BG)
        self.root.minsize(440, 460)
        self._set_icon()
        self._init_fonts()
        self._build_ui()
        self._setup_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.root.bind("<Unmap>", self._on_unmap)
        self.root.after(100, self._drain_ui)
        self.root.after(200, self._tick)
        self.root.after(300, self._startup)
        self.root.after(30000, self._auto_retry_tick)
        self._show_login()
        self.scan_pending()

    # ---------- 基础 UI ----------

    def _set_icon(self) -> None:
        icon = resource_path("assets/app.ico")
        try:
            if icon.is_file():
                self.root.iconbitmap(default=str(icon))
        except Exception:
            pass

    def _init_fonts(self) -> None:
        self.font_title = ctk.CTkFont(family=FAMILY, size=22, weight="bold")
        self.font_section = ctk.CTkFont(family=FAMILY, size=13, weight="bold")
        self.font_body = ctk.CTkFont(family=FAMILY, size=13)
        self.font_small = ctk.CTkFont(family=FAMILY, size=11)
        self.font_tiny = ctk.CTkFont(family=FAMILY, size=10)
        self.font_timer = ctk.CTkFont(family="Segoe UI", size=38, weight="bold")
        self.font_button = ctk.CTkFont(family=FAMILY, size=13, weight="bold")

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self.root, fg_color="transparent", height=54)
        header.pack(fill="x", padx=24, pady=(14, 2))
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left")
        logo_path = resource_path("assets/tray.png")
        self.logo_image = None
        try:
            if logo_path.is_file():
                self.logo_image = ctk.CTkImage(
                    light_image=Image.open(logo_path), size=(28, 28))
                ctk.CTkLabel(brand, text="", image=self.logo_image,
                             width=28).pack(side="left", padx=(0, 9))
            else:
                ctk.CTkLabel(brand, text="●", text_color=BLUE,
                             font=self.font_title).pack(side="left", padx=(0, 8))
        except Exception:
            pass
        ctk.CTkLabel(brand, text="会议记忆", text_color=TEXT,
                     font=self.font_title).pack(side="left")
        ctk.CTkLabel(brand, text="Windows 录音端", text_color=MUTED,
                     font=self.font_small).pack(side="left", padx=(10, 0),
                                                pady=(7, 0))

        self.account_box = ctk.CTkFrame(header, fg_color="transparent")
        self.account_label = ctk.CTkLabel(
            self.account_box, text="", text_color=MUTED, font=self.font_small)
        self.account_label.pack(side="left", padx=(0, 6))
        self.refresh_btn = ctk.CTkButton(
            self.account_box, text="刷新", width=36, height=26,
            corner_radius=8, fg_color="transparent", text_color=BLUE,
            hover_color=SEPARATOR, font=self.font_small,
            command=self.refresh_workspace)
        self.refresh_btn.pack(side="left", padx=(0, 6))
        self.logout_btn = ctk.CTkButton(
            self.account_box, text="退出账号", width=62, height=28,
            corner_radius=14, fg_color="#E9E9EE", text_color=TEXT,
            hover_color="#DEDEE3", font=self.font_small,
            command=self.logout)
        self.logout_btn.pack(side="left")

        self.body = ctk.CTkFrame(self.root, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20, pady=(2, 14))
        self.login_frame = ctk.CTkFrame(self.body, fg_color="transparent")
        self.main_frame = ctk.CTkFrame(self.body, fg_color="transparent")
        self._build_login()
        self._build_main()

    def _build_login(self) -> None:
        card = ctk.CTkFrame(self.login_frame, fg_color=CARD, corner_radius=22)
        card.pack(fill="both", expand=True, padx=24, pady=(8, 8))
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=22, pady=16)
        ctk.CTkFrame(content, fg_color="transparent",
                     height=1).pack(expand=True)

        ctk.CTkLabel(content, text="登录服务器", text_color=TEXT,
                     font=ctk.CTkFont(family=FAMILY, size=22,
                                      weight="bold")).pack(anchor="w")

        self.server_var = tk.StringVar(value=self.config.server)
        self.username_var = tk.StringVar(value=self.config.username)
        self.remember_var = tk.BooleanVar(value=self.config.remember)
        self.trust_var = tk.BooleanVar(value=self.config.trust_self_signed)
        self.password_var = tk.StringVar()

        self.server_entry = self._login_entry(
            content, self.server_var, "服务器地址",
            "例如 http://192.168.110.14:8000")
        self.username_entry = self._login_entry(
            content, self.username_var, "账号", "登录账号")
        self.password_entry = self._login_entry(
            content, self.password_var, "密码", "登录密码", password=True)

        ctk.CTkCheckBox(
            content, text="信任自签 HTTPS 证书",
            variable=self.trust_var, font=self.font_small,
            text_color=TEXT, checkbox_width=18, checkbox_height=18,
            corner_radius=5, border_width=2,
            fg_color=BLUE, hover_color=BLUE_HOVER,
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkCheckBox(
            content, text="记住登录状态（7 天）",
            variable=self.remember_var, font=self.font_small,
            text_color=TEXT, checkbox_width=18, checkbox_height=18,
            corner_radius=5, border_width=2,
            fg_color=BLUE, hover_color=BLUE_HOVER,
        ).pack(anchor="w", pady=(2, 8))

        self.login_btn = ctk.CTkButton(
            content, text="登录并开始", height=42, corner_radius=13,
            fg_color=BLUE, hover_color=BLUE_HOVER, font=self.font_button,
            command=self.do_login)
        self.login_btn.pack(fill="x", pady=(6, 6))
        self.login_status = ctk.CTkLabel(
            content, text="", text_color=MUTED, font=self.font_small,
            anchor="w", justify="left", wraplength=360)
        self.login_status.pack(fill="x")
        ctk.CTkFrame(content, fg_color="transparent",
                     height=1).pack(expand=True)
        self.password_entry.bind("<Return>", lambda event: self.do_login())

    def _login_entry(self, parent, variable: tk.StringVar, label: str,
                     placeholder: str, password: bool = False) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, text_color=MUTED, height=16,
                     font=self.font_tiny).pack(anchor="w", pady=(4, 2))
        entry = ctk.CTkEntry(
            parent, textvariable=variable, height=38, corner_radius=12,
            fg_color=INPUT_BG, border_width=0, text_color=TEXT,
            placeholder_text=placeholder, placeholder_text_color=MUTED,
            font=self.font_body)
        entry.pack(fill="x", pady=(0, 5))
        if password:
            try:
                entry._entry.configure(show="•")
            except Exception:
                pass
        return entry

    def _build_main(self) -> None:
        info_card = ctk.CTkFrame(self.main_frame, fg_color=CARD,
                                 corner_radius=20)
        info_card.pack(fill="x")
        info = ctk.CTkFrame(info_card, fg_color="transparent")
        info.pack(fill="x", padx=18, pady=10)

        self.title_var = tk.StringVar()
        self.title_entry_widget = ctk.CTkEntry(
            info, textvariable=self.title_var, height=34, corner_radius=10,
            fg_color=INPUT_BG, border_width=0, text_color=TEXT,
            placeholder_text="会议主题（可选，留空由纪要自动命名）",
            font=self.font_body)
        self.title_entry_widget.pack(fill="x")

        row = ctk.CTkFrame(info, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        row.grid_columnconfigure(0, weight=1, uniform="col")
        row.grid_columnconfigure(1, weight=1, uniform="col")
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ctk.CTkLabel(left, text="项目", text_color=MUTED, height=16,
                     font=self.font_tiny).pack(anchor="w", pady=(0, 2))
        self.project_var = tk.StringVar()
        self.project_combo = ctk.CTkComboBox(
            left, variable=self.project_var, values=[], height=34,
            corner_radius=10, fg_color=INPUT_BG, border_width=0,
            button_color=INPUT_BG, button_hover_color=SEPARATOR,
            text_color=TEXT, font=self.font_body,
            dropdown_fg_color=CARD, dropdown_hover_color=INPUT_BG,
            dropdown_text_color=TEXT, command=lambda _: self._save_settings())
        self.project_combo.pack(fill="x")

        ctk.CTkLabel(right, text="纪要模板", text_color=MUTED, height=16,
                     font=self.font_tiny).pack(anchor="w", pady=(0, 2))
        self.template_menu = ctk.CTkOptionMenu(
            right, values=[""], height=34, corner_radius=10,
            fg_color=INPUT_BG, button_color=INPUT_BG,
            button_hover_color=SEPARATOR, text_color=TEXT,
            font=self.font_body, dropdown_fg_color=CARD,
            dropdown_hover_color=INPUT_BG, dropdown_text_color=TEXT,
            command=lambda _: self._save_settings())
        self.template_menu.pack(fill="x")

        ctk.CTkLabel(info, text="录音设备", text_color=MUTED, height=16,
                     font=self.font_tiny).pack(anchor="w", pady=(6, 2))
        self.device_menu = ctk.CTkOptionMenu(
            info, values=[""], height=34, corner_radius=10,
            fg_color=INPUT_BG, button_color=INPUT_BG,
            button_hover_color=SEPARATOR, text_color=TEXT,
            font=self.font_body, dropdown_fg_color=CARD,
            dropdown_hover_color=INPUT_BG, dropdown_text_color=TEXT,
            command=lambda _: self._save_settings())
        self.device_menu.pack(fill="x")

        rec_card = ctk.CTkFrame(self.main_frame, fg_color=CARD,
                                corner_radius=20)
        rec_card.pack(fill="x", pady=(12, 0))
        rec = ctk.CTkFrame(rec_card, fg_color="transparent")
        rec.pack(fill="x", padx=18, pady=10)
        self.timer_label = ctk.CTkLabel(
            rec, text="00:00:00", text_color=TEXT, font=self.font_timer)
        self.timer_label.pack()
        self.main_status = ctk.CTkLabel(
            rec, text="准备就绪", text_color=MUTED, font=self.font_small,
            anchor="center", justify="center", wraplength=440)
        self.main_status.pack(fill="x", pady=(0, 6))
        self.level_bar = ctk.CTkProgressBar(
            rec, height=6, corner_radius=3, fg_color=SEPARATOR,
            progress_color=BLUE)
        self.level_bar.set(0)
        self.level_bar.pack(fill="x")
        self.upload_bar = ctk.CTkProgressBar(
            rec, height=4, corner_radius=2, fg_color=SEPARATOR,
            progress_color=BLUE)
        self.upload_bar.set(0)
        self.upload_bar.pack(fill="x", pady=(4, 0))

        controls = ctk.CTkFrame(rec, fg_color="transparent")
        controls.pack(fill="x", pady=(6, 0))
        self.start_btn = ctk.CTkButton(
            controls, text="开始录音", height=42, corner_radius=13,
            fg_color=BLUE, hover_color=BLUE_HOVER, font=self.font_button,
            command=self.start_recording)
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.pause_btn = ctk.CTkButton(
            controls, text="暂停", width=78, height=42, corner_radius=13,
            fg_color="#E9E9EE", hover_color="#DEDEE3", text_color=TEXT,
            font=self.font_body, command=self.toggle_pause)
        self.pause_btn.pack(side="left", padx=8)
        self.stop_btn = ctk.CTkButton(
            controls, text="结束并上传", width=106, height=42,
            corner_radius=13, fg_color=DANGER, hover_color=DANGER_HOVER,
            font=self.font_button, command=self.stop_and_upload)
        self.stop_btn.pack(side="left")

        pending_card = ctk.CTkFrame(self.main_frame, fg_color=CARD,
                                    corner_radius=20)
        pending_card.pack(fill="both", expand=True, pady=(12, 0))
        pending = ctk.CTkFrame(pending_card, fg_color="transparent")
        pending.pack(fill="both", expand=True, padx=18, pady=12)
        pending_head = ctk.CTkFrame(pending, fg_color="transparent")
        pending_head.pack(fill="x")
        ctk.CTkLabel(pending_head, text="待上传录音", text_color=TEXT,
                     font=self.font_section).pack(side="left")
        self.pending_count = ctk.CTkLabel(
            pending_head, text="暂无", text_color=MUTED, font=self.font_tiny)
        self.pending_count.pack(side="left", padx=(6, 0), pady=(2, 0))
        ctk.CTkButton(
            pending_head, text="全部重试", width=62, height=24,
            corner_radius=8, fg_color="transparent", text_color=BLUE,
            hover_color=SEPARATOR, font=self.font_small,
            command=self.retry_all,
        ).pack(side="right")
        self.pending_box = ctk.CTkScrollableFrame(
            pending, fg_color="transparent", height=56,
            scrollbar_button_color="#D1D1D6",
            scrollbar_button_hover_color="#BDBDC2")
        try:
            # CTkScrollbar 默认请求高度会撑高整个列表，限制为可视高度。
            self.pending_box._scrollbar.configure(height=56)
        except Exception:
            pass
        self.pending_empty = ctk.CTkLabel(
            pending, text="暂无待上传录音", text_color=MUTED,
            font=self.font_small)
        self.pending_empty.pack(expand=True, pady=20)

        self._set_controls()

    # ---------- 线程与状态 ----------

    def post(self, callback, *args) -> None:
        self.ui_queue.put((callback, args))

    def _drain_ui(self) -> None:
        try:
            while True:
                callback, args = self.ui_queue.get_nowait()
                try:
                    callback(*args)
                except Exception:
                    logging.exception("ui callback failed")
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(100, self._drain_ui)

    def _set_login_status(self, text: str, kind: str = "muted") -> None:
        self.login_status.configure(text=text, text_color={
            "muted": MUTED, "error": DANGER, "ok": GREEN,
        }.get(kind, MUTED))

    def _set_main_status(self, text: str, kind: str = "muted") -> None:
        self.main_status.configure(text=text, text_color={
            "muted": MUTED, "error": DANGER, "ok": GREEN, "warn": ORANGE,
        }.get(kind, MUTED))

    # ---------- 登录与会话 ----------

    def _startup(self) -> None:
        self.scan_pending()
        session = load_session() if self.config.remember else None
        if not session:
            return
        self._set_login_status("正在恢复登录状态…")
        threading.Thread(target=self._auto_login, args=(session,),
                         daemon=True).start()

    def _auto_login(self, session: dict) -> None:
        if session.get("host") != urlsplit(self.config.server).hostname:
            clear_session()
            self.post(self._set_login_status,
                      "登录状态与当前服务器不一致，请重新登录")
            return
        try:
            api = ApiClient(self.config.server, self.config.trust_self_signed)
            api.set_cookie(session.get("cookie", ""), session.get("host", ""))
            me = api.me()
        except ApiError as exc:
            if exc.status == 401:
                clear_session()
                self.post(self._set_login_status, "登录状态已过期，请重新登录")
            else:
                self.post(self._set_login_status,
                          "自动登录失败：" + exc.message)
            return
        except Exception as exc:
            logging.exception("auto login failed")
            self.post(self._set_login_status, f"自动登录失败：{exc}")
            return
        self.post(self._login_success, api, me, False)

    def do_login(self) -> None:
        server = self.server_var.get().strip()
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not server or not username:
            self._set_login_status("请填写服务器地址和账号", "error")
            return
        self.login_btn.configure(state="disabled", text="正在登录…")
        self._set_login_status("正在连接服务器…")
        threading.Thread(target=self._login_worker,
                         args=(server, username, password), daemon=True).start()

    def _login_worker(self, server: str, username: str, password: str) -> None:
        try:
            api = ApiClient(server, self.trust_var.get())
            api.login(username, password)
            me = api.me()
        except ApiError as exc:
            self.post(self._login_failed, exc.message)
            return
        except Exception as exc:
            logging.exception("login failed")
            self.post(self._login_failed, f"登录失败：{exc}")
            return
        self.post(self._login_success, api, me, True)

    def _login_failed(self, message: str) -> None:
        self.login_btn.configure(state="normal", text="登录并开始")
        self._set_login_status(message, "error")

    def _login_success(self, api: ApiClient, me: dict, manual: bool) -> None:
        if self.api is not None and self.api is not api:
            self.api.close()
        self.api = api
        self.logged_in = True
        self.password_var.set("")
        self.login_btn.configure(state="normal", text="登录并开始")
        self.config.server = api.base
        self.config.username = me.get("username", self.username_var.get())
        self.config.remember = bool(self.remember_var.get())
        self.config.trust_self_signed = bool(self.trust_var.get())
        save_config(self.config)
        if self.config.remember:
            save_session(api.cookie(), api.host, self.config.username)
        else:
            clear_session()
        role = "管理员" if me.get("role") == "admin" else "成员"
        self.account_label.configure(
            text=f"{self.config.username} · {role}")
        self._show_main()
        self._set_main_status("登录成功，正在读取项目与模板…")
        threading.Thread(target=self._load_workspace_worker, daemon=True).start()
        self.refresh_devices()
        self.scan_pending()
        self.root.after(500, self._auto_upload_pending)

    def logout(self) -> None:
        if self.recorder.active:
            messagebox.showwarning(APP_TITLE, "正在录音，请先结束录音后再退出登录。",
                                   parent=self.root)
            return
        if not messagebox.askyesno("退出登录", "确定退出当前账号？",
                                   parent=self.root):
            return
        if self.uploading and not messagebox.askyesno(
                "正在上传", "还有录音正在上传，退出登录会中断上传，确定继续？",
                parent=self.root):
            return
        clear_session()
        if self.api is not None:
            self.api.close()
        self.api = None
        self.logged_in = False
        self.projects = []
        self.templates = []
        self._set_login_status("已退出登录")
        self._show_login()

    # ---------- 工作区数据 ----------

    def _load_workspace_worker(self) -> None:
        try:
            assert self.api is not None
            projects = self.api.projects()
            templates = self.api.templates()
        except ApiError as exc:
            self.post(self._set_main_status, "读取项目失败：" + exc.message, "error")
            return
        except Exception as exc:
            logging.exception("load workspace failed")
            self.post(self._set_main_status, f"读取项目失败：{exc}", "error")
            return
        self.post(self._apply_workspace, projects, templates)

    def _apply_workspace(self, projects: list[dict], templates: list[dict]) -> None:
        self.projects = projects
        names = [item.get("name", "") for item in projects]
        self.project_combo.configure(values=names or [""])
        wanted = self.config.project or self.project_var.get().strip()
        if wanted in names:
            self.project_var.set(wanted)
        elif names:
            self.project_var.set(names[0])

        self.templates = templates
        self.template_by_label = {}
        labels = []
        for item in templates:
            label = item.get("name", item.get("key", ""))
            scene = item.get("scene") or ""
            if scene and scene != label:
                label = f"{label} · {scene}"
            self.template_by_label[label] = item.get("key", "")
            labels.append(label)
        self.template_menu.configure(values=labels or [""])
        current_key = self.config.template
        selected = ""
        for label, key in self.template_by_label.items():
            if key == current_key:
                selected = label
                break
        if not selected and labels:
            selected = labels[0]
        self.template_menu.set(selected or "")
        self._save_settings()
        if self.devices:
            self._set_main_status("准备就绪，可以开始录音")

    def refresh_workspace(self) -> None:
        if not self.logged_in:
            self._show_login()
            return
        self._set_main_status("正在刷新项目、模板与设备…")
        self.refresh_devices()
        threading.Thread(target=self._load_workspace_worker, daemon=True).start()

    def refresh_devices(self) -> None:
        if self.recorder.active:
            return
        try:
            devices = list_input_devices()
        except RecorderError as exc:
            self._set_main_status(str(exc), "error")
            return
        self.devices = devices
        self.device_by_label = {item.label: item for item in devices}
        labels = [item.label for item in devices]
        self.device_menu.configure(values=labels or [""])
        wanted = self.config.device or default_device_key(devices)
        selected = ""
        for item in devices:
            if item.key == wanted:
                selected = item.label
                break
        if not selected and labels:
            selected = labels[0]
        self.device_menu.set(selected or "")
        if devices:
            note = ""
            if not self.config.device:
                note = "已选择系统默认录音设备，可切换外接拾音器。"
            self._set_main_status(note or "准备就绪，可以开始录音")
        else:
            self._set_main_status(
                "未找到可用的录音设备，请检查拾音器连接和 Windows 麦克风权限。",
                "error")
        self._set_controls()

    # ---------- 录音 ----------

    def _selected_device(self):
        device = self.device_by_label.get(self.device_menu.get().strip())
        if device is None and self.devices:
            device = self.devices[0]
        return device

    def _selected_template_key(self) -> str:
        return self.template_by_label.get(self.template_menu.get().strip(), "")

    def _set_controls(self) -> None:
        active = self.recorder.active
        paused = self.recorder.state == "paused"
        can_start = not active and bool(self.devices)
        self.start_btn.configure(
            state="normal" if can_start else "disabled",
            fg_color=BLUE if can_start else "#B9D9FF")
        self.pause_btn.configure(
            state="normal" if active else "disabled",
            text="继续" if paused else "暂停",
            fg_color="#E9E9EE",
            text_color=TEXT if active else MUTED)
        self.stop_btn.configure(
            state="normal" if active else "disabled",
            fg_color=DANGER if active else "#F3B0AC")
        self.title_entry_widget.configure(
            state="disabled" if active else "normal")
        self.project_combo.configure(
            state="disabled" if active else "normal")
        self.template_menu.configure(
            state="disabled" if active else "normal")
        self.device_menu.configure(
            state="disabled" if active else "normal")
        self._update_tray_title()

    def start_recording(self) -> None:
        if not self.logged_in:
            self._show_login()
            return
        if self.recorder.active:
            return
        project = self.project_var.get().strip()
        if not project:
            messagebox.showwarning(APP_TITLE, "请先选择或填写项目名称。",
                                   parent=self.root)
            return
        device = self._selected_device()
        if device is None:
            messagebox.showwarning(APP_TITLE, "没有可用的录音设备。",
                                   parent=self.root)
            return
        if shutil.disk_usage(recordings_dir()).free < 300 * 1024 * 1024:
            messagebox.showwarning(APP_TITLE,
                                   "磁盘剩余空间不足 300 MB，可能无法保存长录音。",
                                   parent=self.root)
            return
        now = datetime.now()
        filename = f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}.wav"
        path = recordings_dir() / filename
        title = self.title_var.get().strip()
        template_key = self._selected_template_key()
        try:
            self.recorder.start(path, device.index)
        except RecorderError as exc:
            self._set_main_status(str(exc), "error")
            messagebox.showerror(APP_TITLE, str(exc), parent=self.root)
            return
        self._write_sidecar(path, {
            "title": title,
            "project": project,
            "template_key": template_key,
            "recorded_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "uploaded": False,
            "uid": "",
            "last_error": "",
        })
        self._save_settings()
        self.upload_bar.set(0)
        self._set_controls()
        note = self.recorder.fallback_note
        self._set_main_status(note or "正在录音，结束后会自动上传。",
                              "warn" if note else "ok")

    def toggle_pause(self) -> None:
        if self.recorder.state == "recording":
            self.recorder.pause()
            self._set_controls()
            self._set_main_status("录音已暂停，点击“继续”恢复。", "warn")
        elif self.recorder.state == "paused":
            try:
                self.recorder.resume()
            except RecorderError as exc:
                self._set_main_status(str(exc), "error")
                return
            self._set_controls()
            self._set_main_status("正在录音，结束后会自动上传。", "ok")

    def stop_and_upload(self) -> None:
        self._stop_recording(upload=True)

    def _stop_recording(self, upload: bool) -> None:
        if not self.recorder.active:
            return
        path = self.recorder.path
        try:
            duration = self.recorder.stop()
        except RecorderError as exc:
            self._set_main_status(str(exc), "error")
            self._set_controls()
            self.scan_pending()
            self.show_window()
            return
        if self.mini is not None:
            self.mini.close()
            self.mini = None
            self.show_window()
        self._set_controls()
        self.level_bar.set(0)
        self.timer_label.configure(text="00:00:00")
        if path is None:
            return
        if duration < 1:
            self._delete_files(path)
            self._set_main_status("录音时间太短，已丢弃。", "warn")
            return
        sidecar = self._read_sidecar(path) or {}
        sidecar["duration_sec"] = round(duration, 1)
        self._write_sidecar(path, sidecar)
        self.scan_pending()
        if upload:
            self._set_main_status("录音已保存，正在上传…", "ok")
            self.queue_upload(path)
        else:
            self._set_main_status("录音已保存到待上传列表。", "warn")

    def _tick(self) -> None:
        if self.recorder.active:
            seconds = int(self.recorder.elapsed())
            self.timer_label.configure(
                text=f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:"
                     f"{seconds % 60:02d}")
            self.level_bar.set(min(1.0, self.recorder.level * 2.6))
        elif self.timer_label.cget("text") != "00:00:00":
            self.timer_label.configure(text="00:00:00")
            self.level_bar.set(0)
        if not self.closing:
            self.root.after(200, self._tick)

    # ---------- 文件与待上传 ----------

    @staticmethod
    def _sidecar_path(path: Path) -> Path:
        return path.with_suffix(".json")

    def _write_sidecar(self, path: Path, data: dict) -> None:
        sidecar = self._sidecar_path(path)
        part = sidecar.with_name(sidecar.name + ".part")
        part.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        os.replace(str(part), str(sidecar))

    def _read_sidecar(self, path: Path) -> dict | None:
        sidecar = self._sidecar_path(path)
        if not sidecar.is_file():
            return None
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _delete_files(self, path: Path) -> None:
        for target in (path, self._sidecar_path(path)):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                logging.exception("delete failed: %s", target)

    def scan_pending(self) -> None:
        self.pending = {}
        for path in sorted(recordings_dir().glob("*.wav")):
            # 进程异常退出时 WAV 头可能仍是 0，统一按实际长度修正。
            repair_wav(path)
            sidecar = self._read_sidecar(path)
            if sidecar is None:
                sidecar = {
                    "title": "",
                    "project": self.config.project or "未归类",
                    "template_key": self.config.template,
                    "recorded_at": datetime.fromtimestamp(
                        path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "uploaded": False,
                    "uid": "",
                    "last_error": "",
                    "recovered": True,
                }
                self._write_sidecar(path, sidecar)
            if sidecar.get("uploaded"):
                # 上传已成功但进程在删除前退出，直接清理。
                self._delete_files(path)
                continue
            self.pending[path] = sidecar
        self._refresh_pending_list()

    def _refresh_pending_list(self) -> None:
        if not hasattr(self, "pending_box"):
            return
        for child in self.pending_box.winfo_children():
            child.destroy()
        items = sorted(self.pending.items(),
                       key=lambda item: item[1].get("recorded_at", ""),
                       reverse=True)
        self.pending_count.configure(
            text=f"{len(items)} 条" if items else "暂无")
        if not items:
            self.pending_box.pack_forget()
            if not self.pending_empty.winfo_ismapped():
                self.pending_empty.pack(expand=True, pady=20)
            self._update_tray_title()
            return
        self.pending_empty.pack_forget()
        if not self.pending_box.winfo_ismapped():
            self.pending_box.pack(fill="both", expand=True, pady=(6, 0))
        for path, data in items:
            row = ctk.CTkFrame(self.pending_box, fg_color="#F7F7FA",
                               corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True,
                      padx=(10, 4), pady=5)
            ctk.CTkLabel(
                left, text=data.get("title") or path.stem, text_color=TEXT,
                font=self.font_small, anchor="w").pack(anchor="w", fill="x")
            state = "上次上传失败" if data.get("last_error") else "待上传"
            ctk.CTkLabel(
                left, text=f"{data.get('recorded_at', '')} · {state}",
                text_color=MUTED, font=self.font_tiny,
                anchor="w").pack(anchor="w", fill="x")
            ctk.CTkButton(
                row, text="删除", width=40, height=24, corner_radius=8,
                fg_color="transparent", text_color=MUTED,
                hover_color=SEPARATOR, font=self.font_tiny,
                command=lambda p=path: self.delete_path(p),
            ).pack(side="right", padx=(0, 6))
            ctk.CTkButton(
                row, text="重试", width=40, height=24, corner_radius=8,
                fg_color="transparent", text_color=BLUE,
                hover_color=SEPARATOR, font=self.font_tiny,
                command=lambda p=path: self.queue_upload(p),
            ).pack(side="right")
        self._update_tray_title()

    def retry_all(self) -> None:
        for path in list(self.pending):
            self.queue_upload(path)

    def delete_path(self, path: Path) -> None:
        if not messagebox.askyesno(APP_TITLE, "确定删除这条本地录音？",
                                   parent=self.root):
            return
        self._delete_files(path)
        self.scan_pending()

    # ---------- 上传与状态 ----------

    def _auto_upload_pending(self) -> None:
        if self.logged_in and self.pending:
            self.queue_upload(next(iter(self.pending)))

    def _auto_retry_tick(self) -> None:
        if self.logged_in and not self.uploading and self.pending:
            now = time.time()
            for path in list(self.pending):
                if now - self.last_attempt.get(path, 0) >= 60:
                    self.queue_upload(path)
                    break
        if not self.closing:
            self.root.after(30000, self._auto_retry_tick)

    def queue_upload(self, path: Path) -> None:
        if not self.logged_in or self.api is None:
            self._set_main_status("请先登录后再上传。", "warn")
            return
        if not path.is_file() or path in self.queued:
            return
        self.queued.add(path)
        self.upload_queue.append(path)
        self._pump_uploads()

    def _pump_uploads(self) -> None:
        if self.uploading or not self.upload_queue:
            return
        path = self.upload_queue.pop(0)
        self.uploading = True
        self.last_attempt[path] = time.time()
        threading.Thread(target=self._upload_worker, args=(path,),
                         daemon=True).start()

    def _upload_worker(self, path: Path) -> None:
        sidecar = self._read_sidecar(path) or {}
        project = str(sidecar.get("project") or self.config.project).strip()
        if not project:
            self.post(self._upload_finished, path, "没有项目名称，无法上传", None)
            return
        fields = {
            "title": sidecar.get("title", ""),
            "project_name": project,
            "template_key": sidecar.get("template_key", ""),
            "recorded_at": sidecar.get("recorded_at", ""),
        }
        try:
            assert self.api is not None
            api = self.api
            result = api.upload(
                str(path), fields,
                progress=lambda percent: self.post(
                    self._upload_progress, path, percent))
        except ApiError as exc:
            logging.warning("upload failed %s: %s", path, exc.message)
            self.post(self._upload_finished, path, exc.message, None)
            return
        except Exception as exc:
            logging.exception("upload failed")
            self.post(self._upload_finished, path, f"上传失败：{exc}", None)
            return
        uid = str(result.get("uid") or "")
        sidecar = self._read_sidecar(path) or {}
        sidecar["uid"] = uid
        sidecar["uploaded"] = True
        sidecar["last_error"] = ""
        self._write_sidecar(path, sidecar)
        self.post(self._upload_finished, path, None, uid)

    def _upload_progress(self, path: Path, percent: int) -> None:
        self.upload_bar.set(percent / 100)
        self._set_main_status(f"正在上传：{percent}%", "ok")

    def _upload_finished(self, path: Path, error: str | None, uid: str | None) -> None:
        self.uploading = False
        self.queued.discard(path)
        self.upload_bar.set(0)
        if error:
            sidecar = self._read_sidecar(path) or {}
            sidecar["last_error"] = error
            self._write_sidecar(path, sidecar)
            self._set_main_status("上传失败：" + error + "（已加入待上传列表）", "error")
            self.scan_pending()
        else:
            self._delete_files(path)
            self._set_main_status("上传完成，服务器正在生成会议纪要…", "ok")
            self.scan_pending()
            if uid:
                threading.Thread(target=self._poll_meeting,
                                 args=(uid,), daemon=True).start()
        self._pump_uploads()

    def _poll_meeting(self, uid: str) -> None:
        while self.logged_in and self.api is not None and not self.closing:
            try:
                data = self.api.status(uid)
            except ApiError as exc:
                self.post(self._set_main_status,
                          "查询处理状态失败：" + exc.message, "warn")
                return
            except Exception as exc:
                logging.exception("poll status failed")
                self.post(self._set_main_status, f"查询处理状态失败：{exc}", "warn")
                return
            status = data.get("status", "")
            label = data.get("status_label") or STATUS_TEXT.get(status, status)
            if status == "done":
                self.post(self._set_main_status,
                          "纪要已生成，可在网页端或手机 App 查看。", "ok")
                self.post(self._notify, "纪要已生成", "会议记忆录音端")
                return
            if status == "failed":
                code = data.get("error_code") or ""
                message = data.get("error_msg") or ""
                hint = FAILURE_HINTS.get(code, "")
                text = f"处理失败：{hint or message or code or '未知原因'}"
                self.post(self._set_main_status, text, "error")
                self.post(self._notify, "纪要生成失败", hint or message or code)
                return
            self.post(self._set_main_status,
                      f"服务器处理中：{label}（录音已安全上传）", "muted")
            time.sleep(3)

    def _notify(self, title: str, message: str) -> None:
        if self.tray is None:
            return
        try:
            self.tray.notify(message, title)
        except Exception:
            pass

    # ---------- 托盘、悬浮窗与窗口 ----------

    def _tray_image(self):
        path = resource_path("assets/tray.png")
        if path.is_file():
            return Image.open(path)
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        draw.ellipse((2, 2, 62, 62), fill=(0, 122, 255, 255))
        draw.rounded_rectangle((26, 14, 38, 38), radius=6, fill="white")
        draw.arc((18, 30, 46, 50), start=0, end=180, fill="white", width=4)
        draw.line((32, 48, 32, 54), fill="white", width=4)
        draw.line((24, 54, 40, 54), fill="white", width=4)
        return image

    def _setup_tray(self) -> None:
        try:
            import pystray
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", lambda: self.post(self.show_window),
                                 default=True),
                pystray.MenuItem("开始录音",
                                 lambda: self.post(self._tray_start)),
                pystray.MenuItem("暂停 / 继续",
                                 lambda: self.post(self.toggle_pause)),
                pystray.MenuItem("结束并上传",
                                 lambda: self.post(self._tray_stop)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", lambda: self.post(self.request_quit)),
            )
            self.tray = pystray.Icon(
                "meeting-memory-recorder", self._tray_image(),
                "会议记忆录音端", menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception:
            logging.exception("tray init failed")
            self.tray = None

    def _update_tray_title(self) -> None:
        if self.tray is None:
            return
        title = "会议记忆录音端"
        if self.recorder.state == "recording":
            seconds = int(self.recorder.elapsed())
            title += f" · 录音中 {seconds // 60:02d}:{seconds % 60:02d}"
        elif self.recorder.state == "paused":
            title += " · 已暂停"
        elif self.pending:
            title += f" · {len(self.pending)} 条待上传"
        try:
            self.tray.title = title
            self.tray.update_menu()
        except Exception:
            pass

    def _tray_start(self) -> None:
        if self.recorder.active:
            self.show_window()
            return
        if not self.logged_in:
            self.show_window()
            self._show_login()
            return
        self.show_window()
        self.start_recording()

    def _tray_stop(self) -> None:
        if not self.recorder.active:
            self.show_window()
            return
        self.stop_and_upload()

    def show_mini(self) -> None:
        if not self.recorder.active:
            return
        self.root.withdraw()
        if self.mini is None:
            self.mini = MiniRecorder(self)
        self.mini.show()

    def restore_from_mini(self) -> None:
        self.show_window()

    def hide_to_tray(self) -> None:
        self._save_settings()
        if self.recorder.active:
            self.show_mini()
            return
        if self.tray is None:
            self.root.iconify()
            return
        self.root.withdraw()
        if not self._tray_notified:
            self._tray_notified = True
            self._notify("会议记忆录音端", "已最小化到托盘，点击图标可恢复窗口。")

    def _on_unmap(self, event) -> None:
        if event.widget is not self.root or self.root.state() != "iconic":
            return
        if self.tray is None and not self.recorder.active:
            return
        self.root.after(20, self.show_mini if self.recorder.active
                        else self.root.withdraw)

    def show_window(self) -> None:
        if self.mini is not None:
            self.mini.close()
            self.mini = None
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def request_quit(self) -> None:
        if self.mini is not None:
            self.show_window()
        if self.recorder.active:
            if not messagebox.askyesno(
                    APP_TITLE,
                    "正在录音。结束录音并退出？\n录音会保存在待上传列表，"
                    "下次启动可继续上传。",
                    parent=self.root):
                return
            self._stop_recording(upload=False)
        self._save_settings()
        self.closing = True
        if self.mini is not None:
            self.mini.close()
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.recorder.shutdown()
        if self.api is not None:
            self.api.close()
        self.root.destroy()

    def _save_settings(self) -> None:
        try:
            self.config.project = self.project_var.get().strip()
            self.config.template = self._selected_template_key()
            device = self.device_by_label.get(self.device_menu.get().strip())
            if device is not None:
                self.config.device = device.key
            self.config.server = self.server_var.get().strip() or self.config.server
            self.config.username = self.username_var.get().strip() or self.config.username
            self.config.remember = bool(self.remember_var.get())
            self.config.trust_self_signed = bool(self.trust_var.get())
            if self.logged_in and self.root.state() != "withdrawn":
                self.config.geometry = self.root.winfo_geometry()
            save_config(self.config)
        except Exception:
            logging.exception("save config failed")

    def _show_login(self) -> None:
        self.main_frame.pack_forget()
        self.login_frame.pack(fill="both", expand=True)
        self.account_box.pack_forget()
        self.root.minsize(440, 460)
        self._resize(480, 520)
        self.root.after(50, self.password_entry.focus_set)

    def _show_main(self) -> None:
        self.login_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True)
        self.account_box.pack(side="right")
        self.root.minsize(600, 640)
        self._resize(620, 672)
        self._set_controls()

    def _resize(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(width, max(480, screen_w - 40))
        height = min(height, max(560, screen_h - 80))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")


def run_self_test() -> int:
    lines = []
    try:
        devices = list_input_devices()
        lines.append(f"devices={len(devices)}")
        for device in devices:
            lines.append(f"{device.index}\t{device.key}\t"
                         f"{device.max_channels}\t{device.default_rate}")
    except Exception as exc:
        lines.append(f"error={exc}")
    path = Path(tempfile.gettempdir()) / "mm_recorder_selftest.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return 0


def acquire_single_instance():
    try:
        import ctypes
        handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, "MeetingMemoryRecorder_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:
            return None
        return handle
    except Exception:
        return object()


def main() -> int:
    setup_logging()
    if "--self-test" in sys.argv:
        return run_self_test()
    mutex = acquire_single_instance()
    if mutex is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_TITLE, "会议记忆录音端已经在运行。")
        root.destroy()
        return 0
    ctk.set_appearance_mode("light")
    root = ctk.CTk()
    # 小屏笔记本上略微缩小控件，保证登录与录音界面都能在一屏内显示。
    scale = min(1.0, max(0.8, (root.winfo_screenheight() - 110) / 760))
    if scale < 0.98:
        ctk.set_widget_scaling(scale)
    app = RecorderApp(root)
    try:
        root.mainloop()
    finally:
        app.closing = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
