"""
Law Minister's Office — AI Attendance Engine
Standalone Desktop GUI Application

This is the main GUI for the office PC. It provides:
- Camera configuration (add/edit/remove RTSP cameras)
- Cloud connection status
- Engine start/stop controls
- Live attendance feed
- System tray background operation
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    CTK = True
except ImportError:
    ctk = None
    CTK = False

from office_engine.config import load_config, save_config, CONFIG_FILE, DEFAULT_CONFIG
from office_engine.engine import AttendanceEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("office_engine.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("office_engine.gui")

IST = timezone(timedelta(hours=5, minutes=30))

# Color scheme
NAVY = "#1B2A4A"
GOLD = "#C5A55A"
DARK_BG = "#0d1117"
CARD_BG = "#161b22"
ACCENT = "#1f6feb"
TEXT = "#e6edf3"
TEXT_DIM = "#8b949e"
SUCCESS = "#3fb950"
DANGER = "#f85149"
WARNING = "#d29922"
BORDER = "#30363d"


class OfficeEngineApp:
    """Main GUI application for the office attendance engine."""

    def __init__(self):
        self.engine: AttendanceEngine | None = None
        self._engine_thread: threading.Thread | None = None
        self._running = False
        self._log_lines: list[str] = []

        # Load or create config
        if not CONFIG_FILE.exists():
            save_config(DEFAULT_CONFIG)

        self.cfg = load_config()
        self._build_ui()

    def _build_ui(self):
        if CTK:
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()

        self.root.title("Law Minister's Office — AI Attendance Engine")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        if not CTK:
            self.root.configure(bg=DARK_BG)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Main container
        main = self._frame(self.root)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        self._build_header(main)

        # Notebook / tabs
        if CTK:
            self.notebook = ctk.CTkTabview(main, fg_color=CARD_BG)
        else:
            style = ttk.Style()
            style.configure("TNotebook", background=DARK_BG)
            self.notebook = ttk.Notebook(main)

        self.notebook.pack(fill="both", expand=True, pady=(10, 0))

        # Tabs
        self._build_status_tab()
        self._build_cameras_tab()
        self._build_settings_tab()
        self._build_log_tab()

        # Start periodic UI updates
        self._update_status()

    def _frame(self, parent, **kw):
        if CTK:
            return ctk.CTkFrame(parent, fg_color=kw.get("bg", DARK_BG))
        else:
            return tk.Frame(parent, bg=kw.get("bg", DARK_BG))

    def _label(self, parent, text, **kw):
        font_size = kw.pop("font_size", 12)
        color = kw.pop("color", TEXT)
        bold = kw.pop("bold", False)
        font = ("Segoe UI", font_size, "bold" if bold else "normal")
        if CTK:
            return ctk.CTkLabel(parent, text=text, font=font, text_color=color, **kw)
        else:
            return tk.Label(parent, text=text, font=font, fg=color, bg=DARK_BG, **kw)

    def _button(self, parent, text, command, **kw):
        color = kw.pop("color", ACCENT)
        if CTK:
            return ctk.CTkButton(
                parent, text=text, command=command,
                fg_color=color, hover_color=NAVY, **kw
            )
        else:
            return tk.Button(
                parent, text=text, command=command,
                bg=color, fg=TEXT, relief="flat", **kw
            )

    def _entry(self, parent, **kw):
        width = kw.pop("width", 300)
        if CTK:
            return ctk.CTkEntry(parent, width=width, **kw)
        else:
            return tk.Entry(parent, width=width // 8, **kw)

    # ── Header ──

    def _build_header(self, parent):
        header = self._frame(parent, bg=NAVY)
        header.pack(fill="x", pady=(0, 5))

        title = self._label(
            header, "Law Minister's Office — AI Attendance Engine",
            font_size=16, bold=True, color=GOLD,
        )
        title.pack(side="left", padx=15, pady=10)

        # IST clock
        self.clock_label = self._label(
            header, "", font_size=11, color=TEXT_DIM,
        )
        self.clock_label.pack(side="right", padx=15, pady=10)

        # Engine control buttons
        btn_frame = self._frame(header, bg=NAVY)
        btn_frame.pack(side="right", padx=10)

        self.start_btn = self._button(
            btn_frame, "▶ Start Engine", self._start_engine, color=SUCCESS
        )
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = self._button(
            btn_frame, "■ Stop Engine", self._stop_engine, color=DANGER
        )
        self.stop_btn.pack(side="left", padx=5)

    # ── Status Tab ──

    def _build_status_tab(self):
        if CTK:
            tab = self.notebook.add("Status")
        else:
            tab = tk.Frame(self.notebook, bg=DARK_BG)
            self.notebook.add(tab, text="Status")

        # Status cards
        cards = self._frame(tab)
        cards.pack(fill="x", padx=10, pady=10)

        self.status_vars = {}
        card_data = [
            ("engine_status", "Engine", "Stopped"),
            ("cloud_status", "Cloud", "Unknown"),
            ("cameras_connected", "Cameras", "0 / 0"),
            ("known_faces", "Known Faces", "0"),
            ("today_attendance", "Today's Attendance", "0"),
            ("frames_processed", "Frames Processed", "0"),
        ]

        for i, (key, title, default) in enumerate(card_data):
            card = self._frame(cards, bg=CARD_BG)
            card.grid(row=i // 3, column=i % 3, padx=5, pady=5, sticky="nsew")
            cards.grid_columnconfigure(i % 3, weight=1)

            self._label(card, title, font_size=10, color=TEXT_DIM).pack(pady=(10, 2))
            var = tk.StringVar(value=default)
            self.status_vars[key] = var
            self._label(card, "", font_size=16, bold=True, textvariable=var).pack(pady=(2, 10))

        # Recent attendance feed
        feed_frame = self._frame(tab)
        feed_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self._label(feed_frame, "Recent Attendance", font_size=13, bold=True).pack(
            anchor="w", pady=(5, 5)
        )

        if CTK:
            self.feed_text = ctk.CTkTextbox(feed_frame, height=200, fg_color=CARD_BG)
        else:
            self.feed_text = tk.Text(
                feed_frame, height=10, bg=CARD_BG, fg=TEXT, relief="flat"
            )
        self.feed_text.pack(fill="both", expand=True)

    # ── Cameras Tab ──

    def _build_cameras_tab(self):
        if CTK:
            tab = self.notebook.add("Cameras")
        else:
            tab = tk.Frame(self.notebook, bg=DARK_BG)
            self.notebook.add(tab, text="Cameras")

        # Camera list
        list_frame = self._frame(tab)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self._label(list_frame, "Configured Cameras", font_size=13, bold=True).pack(
            anchor="w", pady=(5, 5)
        )

        # Treeview for cameras
        columns = ("name", "type", "url", "enabled")
        self.cam_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", height=8
        )
        self.cam_tree.heading("name", text="Name")
        self.cam_tree.heading("type", text="Type")
        self.cam_tree.heading("url", text="URL / Source")
        self.cam_tree.heading("enabled", text="Enabled")
        self.cam_tree.column("name", width=150)
        self.cam_tree.column("type", width=80)
        self.cam_tree.column("url", width=400)
        self.cam_tree.column("enabled", width=80)
        self.cam_tree.pack(fill="both", expand=True)

        self._refresh_camera_list()

        # Camera add/edit/remove buttons
        btn_frame = self._frame(tab)
        btn_frame.pack(fill="x", padx=10, pady=5)

        self._button(btn_frame, "+ Add Camera", self._add_camera_dialog).pack(
            side="left", padx=5
        )
        self._button(
            btn_frame, "Edit Camera", self._edit_camera_dialog
        ).pack(side="left", padx=5)
        self._button(
            btn_frame, "Remove Camera", self._remove_camera, color=DANGER
        ).pack(side="left", padx=5)
        self._button(
            btn_frame, "Test Connection", self._test_camera_connection, color=WARNING
        ).pack(side="right", padx=5)

    def _refresh_camera_list(self):
        for item in self.cam_tree.get_children():
            self.cam_tree.delete(item)
        cameras = self.cfg.get("cameras", [])
        for cam in cameras:
            self.cam_tree.insert("", "end", values=(
                cam.get("name", ""),
                cam.get("type", "rtsp"),
                cam.get("url", ""),
                "Yes" if cam.get("enabled", True) else "No",
            ))

    def _add_camera_dialog(self):
        self._camera_dialog("Add Camera")

    def _edit_camera_dialog(self):
        sel = self.cam_tree.selection()
        if not sel:
            messagebox.showwarning("Select Camera", "Please select a camera to edit.")
            return
        idx = self.cam_tree.index(sel[0])
        cam = self.cfg["cameras"][idx]
        self._camera_dialog("Edit Camera", cam, idx)

    def _camera_dialog(self, title, cam=None, idx=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("500x350")
        dialog.transient(self.root)
        dialog.grab_set()

        if not CTK:
            dialog.configure(bg=DARK_BG)

        fields = {}
        labels = [
            ("name", "Camera Name:", cam.get("name", "") if cam else ""),
            ("type", "Type (rtsp/webcam):", cam.get("type", "rtsp") if cam else "rtsp"),
            ("url", "RTSP URL:", cam.get("url", "") if cam else ""),
        ]

        for i, (key, label, default) in enumerate(labels):
            self._label(dialog, label, font_size=11).grid(
                row=i, column=0, padx=10, pady=8, sticky="w"
            )
            entry = self._entry(dialog, width=350)
            entry.grid(row=i, column=1, padx=10, pady=8)
            if CTK:
                entry.insert(0, default)
            else:
                entry.insert(0, default)
            fields[key] = entry

        # Enabled checkbox
        enabled_var = tk.BooleanVar(value=cam.get("enabled", True) if cam else True)
        if CTK:
            cb = ctk.CTkCheckBox(dialog, text="Enabled", variable=enabled_var)
        else:
            cb = tk.Checkbutton(
                dialog, text="Enabled", variable=enabled_var,
                bg=DARK_BG, fg=TEXT, selectcolor=CARD_BG,
            )
        cb.grid(row=len(labels), column=1, padx=10, pady=8, sticky="w")

        def save():
            new_cam = {
                "name": fields["name"].get().strip(),
                "type": fields["type"].get().strip(),
                "url": fields["url"].get().strip(),
                "enabled": enabled_var.get(),
            }
            if not new_cam["name"]:
                messagebox.showwarning("Name Required", "Please enter a camera name.")
                return

            cameras = self.cfg.get("cameras", [])
            if idx is not None:
                cameras[idx] = new_cam
            else:
                cameras.append(new_cam)

            self.cfg["cameras"] = cameras
            save_config(self.cfg)
            self._refresh_camera_list()
            dialog.destroy()
            self._log(f"Camera saved: {new_cam['name']}")

        self._button(dialog, "Save", save, color=SUCCESS).grid(
            row=len(labels) + 1, column=1, padx=10, pady=15, sticky="e"
        )

    def _remove_camera(self):
        sel = self.cam_tree.selection()
        if not sel:
            messagebox.showwarning("Select Camera", "Please select a camera to remove.")
            return
        idx = self.cam_tree.index(sel[0])
        cam_name = self.cfg["cameras"][idx]["name"]
        if messagebox.askyesno("Confirm", f"Remove camera '{cam_name}'?"):
            self.cfg["cameras"].pop(idx)
            save_config(self.cfg)
            self._refresh_camera_list()
            self._log(f"Camera removed: {cam_name}")

    def _test_camera_connection(self):
        sel = self.cam_tree.selection()
        if not sel:
            messagebox.showwarning("Select Camera", "Please select a camera to test.")
            return
        idx = self.cam_tree.index(sel[0])
        cam = self.cfg["cameras"][idx]

        import cv2
        url = cam.get("url", "")
        if cam.get("type") == "webcam":
            url = cam.get("device_id", 0)

        self._log(f"Testing camera: {cam['name']}...")

        def test():
            try:
                cap = cv2.VideoCapture(url)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret:
                        self._log(f"Camera '{cam['name']}' — connected OK")
                        self.root.after(0, lambda: messagebox.showinfo(
                            "Success", f"Camera '{cam['name']}' connected successfully!"
                        ))
                    else:
                        self._log(f"Camera '{cam['name']}' — connected but no frame")
                        self.root.after(0, lambda: messagebox.showwarning(
                            "Partial", f"Camera '{cam['name']}' opened but couldn't grab a frame."
                        ))
                else:
                    self._log(f"Camera '{cam['name']}' — connection failed")
                    self.root.after(0, lambda: messagebox.showerror(
                        "Failed", f"Could not connect to camera '{cam['name']}'.\nCheck the URL and credentials."
                    ))
            except Exception as e:
                self._log(f"Camera test error: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

        threading.Thread(target=test, daemon=True).start()

    # ── Settings Tab ──

    def _build_settings_tab(self):
        if CTK:
            tab = self.notebook.add("Settings")
        else:
            tab = tk.Frame(self.notebook, bg=DARK_BG)
            self.notebook.add(tab, text="Settings")

        settings_frame = self._frame(tab)
        settings_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.setting_vars = {}
        settings = [
            ("cloud_url", "Cloud Bot URL", self.cfg["cloud_url"]),
            ("sync_interval_seconds", "Sync Interval (seconds)", str(self.cfg["sync_interval_seconds"])),
            ("snapshot_interval_seconds", "Frame Capture Interval (seconds)", str(self.cfg["snapshot_interval_seconds"])),
            ("recognition_threshold", "Recognition Threshold", str(self.cfg["recognition_threshold"])),
            ("cooldown_seconds", "Cooldown (seconds)", str(self.cfg["cooldown_seconds"])),
            ("attendance_start_hour", "Attendance Start Hour", str(self.cfg["attendance_start_hour"])),
            ("attendance_end_hour", "Attendance End Hour", str(self.cfg["attendance_end_hour"])),
        ]

        for i, (key, label, default) in enumerate(settings):
            self._label(settings_frame, label, font_size=11).grid(
                row=i, column=0, padx=10, pady=6, sticky="w"
            )
            entry = self._entry(settings_frame, width=400)
            entry.grid(row=i, column=1, padx=10, pady=6, sticky="w")
            if CTK:
                entry.insert(0, default)
            else:
                entry.insert(0, default)
            self.setting_vars[key] = entry

        def save_settings():
            for key, entry in self.setting_vars.items():
                val = entry.get().strip()
                if key in ("sync_interval_seconds", "snapshot_interval_seconds",
                           "cooldown_seconds", "attendance_start_hour",
                           "attendance_end_hour"):
                    try:
                        val = int(val)
                    except ValueError:
                        messagebox.showwarning("Invalid", f"{key} must be a number.")
                        return
                elif key == "recognition_threshold":
                    try:
                        val = float(val)
                    except ValueError:
                        messagebox.showwarning("Invalid", f"{key} must be a decimal.")
                        return
                self.cfg[key] = val

            save_config(self.cfg)
            self._log("Settings saved")
            messagebox.showinfo("Saved", "Settings saved successfully.")

        self._button(settings_frame, "Save Settings", save_settings, color=SUCCESS).grid(
            row=len(settings), column=1, padx=10, pady=15, sticky="e"
        )

    # ── Log Tab ──

    def _build_log_tab(self):
        if CTK:
            tab = self.notebook.add("Log")
        else:
            tab = tk.Frame(self.notebook, bg=DARK_BG)
            self.notebook.add(tab, text="Log")

        if CTK:
            self.log_text = ctk.CTkTextbox(tab, fg_color=CARD_BG)
        else:
            self.log_text = tk.Text(tab, bg=CARD_BG, fg=TEXT, relief="flat")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)

        btn_frame = self._frame(tab)
        btn_frame.pack(fill="x", padx=10, pady=5)
        self._button(btn_frame, "Clear Log", self._clear_log).pack(side="right")

    def _log(self, msg: str):
        now = datetime.now(IST).strftime("%H:%M:%S IST")
        line = f"[{now}] {msg}"
        self._log_lines.append(line)
        logger.info(msg)

        try:
            if CTK:
                self.log_text.insert("end", line + "\n")
            else:
                self.log_text.insert("end", line + "\n")
                self.log_text.see("end")
        except Exception:
            pass

    def _clear_log(self):
        self._log_lines.clear()
        if CTK:
            self.log_text.delete("0.0", "end")
        else:
            self.log_text.delete("1.0", "end")

    # ── Engine Control ──

    def _start_engine(self):
        if self._running:
            self._log("Engine is already running")
            return

        self.cfg = load_config()
        cameras = [c for c in self.cfg.get("cameras", []) if c.get("enabled", True)]
        if not cameras:
            messagebox.showwarning(
                "No Cameras",
                "No enabled cameras configured.\nGo to the Cameras tab to add one.",
            )
            return

        self._running = True
        self._log("Starting attendance engine...")

        def run_engine():
            self.engine = AttendanceEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.engine.run())
            except Exception as e:
                self._log(f"Engine error: {e}")
            finally:
                self._running = False
                loop.close()

        self._engine_thread = threading.Thread(target=run_engine, daemon=True)
        self._engine_thread.start()
        self._log("Engine started")

    def _stop_engine(self):
        if not self._running:
            self._log("Engine is not running")
            return

        self._log("Stopping engine...")
        if self.engine:
            self.engine.stop()
        self._running = False
        self._log("Engine stopped")

    # ── Periodic Updates ──

    def _update_status(self):
        # Update clock
        now = datetime.now(IST)
        self.clock_label.configure(text=now.strftime("%d-%m-%Y %H:%M:%S IST"))

        # Update status cards
        if self._running and self.engine:
            stats = self.engine.stats
            self.status_vars["engine_status"].set("Running")
            self.status_vars["known_faces"].set(str(len(self.engine.known_embeddings)))
            self.status_vars["frames_processed"].set(str(stats.get("frames_processed", 0)))
            self.status_vars["today_attendance"].set(str(stats.get("matches_found", 0)))
            self.status_vars["cameras_connected"].set(
                f"{self.engine.camera.connected_count} / {len(self.engine.camera.cameras)}"
            )
            last_sync = stats.get("last_sync", "Never")
            self.status_vars["cloud_status"].set(
                f"Synced: {last_sync}" if last_sync else "Connected"
            )
        else:
            self.status_vars["engine_status"].set("Stopped")

        self.root.after(2000, self._update_status)

    def _on_close(self):
        if self._running:
            if messagebox.askyesno(
                "Confirm Exit",
                "The attendance engine is running.\nStop engine and exit?",
            ):
                self._stop_engine()
                self.root.destroy()
        else:
            self.root.destroy()

    def run(self):
        self._log("Application started")
        self._log(f"Cloud URL: {self.cfg['cloud_url']}")
        self._log(f"Cameras configured: {len(self.cfg.get('cameras', []))}")
        self.root.mainloop()


def main():
    app = OfficeEngineApp()
    app.run()


if __name__ == "__main__":
    main()
