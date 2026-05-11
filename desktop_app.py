"""
Law Minister's Office — AI-Powered Staff Attendance System
Standalone Desktop Application

Run: python desktop_app.py
"""

import csv
import io
import logging
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    CTK = True
except ImportError:
    ctk = None
    CTK = False

from backend import database as db
from backend import face_engine
from backend import camera as cam
from backend import whatsapp as wa
from backend.config import load_config, save_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("attendance.desktop")

FACE_IMAGES_DIR = Path(__file__).parent / "face_images"
FACE_IMAGES_DIR.mkdir(exist_ok=True)
ATTENDANCE_SNAPSHOTS_DIR = Path(__file__).parent / "attendance_snapshots"
ATTENDANCE_SNAPSHOTS_DIR.mkdir(exist_ok=True)

# ─── Color scheme ───
NAVY = "#1B2A4A"
GOLD = "#C5A55A"
DARK_BG = "#1a1a2e"
CARD_BG = "#16213e"
ACCENT = "#0f3460"
TEXT = "#e0e0e0"
TEXT_DIM = "#8892a0"
SUCCESS = "#27ae60"
DANGER = "#e74c3c"
WARNING = "#f39c12"
BLUE = "#3498db"


class AttendanceDesktopEngine:
    """Background attendance monitoring engine for the desktop app."""

    def __init__(self, app_ref):
        self.app = app_ref
        self.running = False
        self._thread = None
        self._cooldowns: dict[str, float] = {}
        self.stats = {
            "frames_processed": 0,
            "faces_detected": 0,
            "matches_found": 0,
            "started_at": None,
            "last_frame_at": None,
        }

    def _is_in_window(self) -> bool:
        cfg = load_config()
        now = datetime.now()
        start = now.replace(
            hour=cfg["attendance_start_hour"],
            minute=cfg["attendance_start_minute"],
            second=0,
        )
        end = now.replace(
            hour=cfg["attendance_end_hour"],
            minute=cfg["attendance_end_minute"],
            second=0,
        )
        return start <= now <= end

    def _check_cooldown(self, staff_id: str) -> bool:
        cfg = load_config()
        cooldown = cfg.get("cooldown_seconds", 300)
        last = self._cooldowns.get(staff_id, 0)
        return (time.time() - last) < cooldown

    def _set_cooldown(self, staff_id: str):
        self._cooldowns[staff_id] = time.time()

    def _process_frame(self, image_bytes: bytes, camera_name: str) -> list[dict]:
        cfg = load_config()
        threshold = cfg.get("recognition_threshold", 0.45)

        enhanced = face_engine.preprocess_image(image_bytes)
        detections = face_engine.detect_and_encode(enhanced)
        self.stats["frames_processed"] += 1
        self.stats["last_frame_at"] = datetime.now().isoformat()

        if not detections:
            return []

        self.stats["faces_detected"] += len(detections)
        records = []

        for embedding, cropped_face, bbox in detections:
            match = face_engine.match_face(embedding, threshold=threshold)
            if match is None:
                continue

            staff_id, name, confidence = match

            if self._check_cooldown(staff_id):
                continue
            self._set_cooldown(staff_id)

            ts = int(time.time())
            snap_filename = f"{staff_id}_{ts}.jpg"
            snap_path = ATTENDANCE_SNAPSHOTS_DIR / snap_filename
            with open(snap_path, "wb") as f:
                f.write(cropped_face)

            log_id = db.log_attendance(
                staff_id=staff_id,
                name=name,
                confidence=confidence,
                snapshot_path=str(snap_path),
                camera_source=camera_name,
            )

            self.stats["matches_found"] += 1
            record = {
                "log_id": log_id,
                "staff_id": staff_id,
                "name": name,
                "confidence": round(confidence, 4),
                "camera": camera_name,
                "time": datetime.now().strftime("%H:%M:%S"),
            }
            records.append(record)
            logger.info(
                f"Attendance: {name} ({staff_id}) — "
                f"confidence={confidence:.3f} camera={camera_name}"
            )

        return records

    def _run_loop(self):
        logger.info("Attendance engine started")
        self.stats["started_at"] = datetime.now().isoformat()

        while self.running:
            cfg = load_config()
            interval = cfg.get("snapshot_interval_seconds", 5)
            cameras = db.get_cameras(active_only=True)

            if not cameras:
                time.sleep(interval)
                continue

            if not self._is_in_window():
                time.sleep(30)
                continue

            for camera_cfg in cameras:
                if not self.running:
                    break
                try:
                    image_bytes = cam.capture_from_camera(camera_cfg)
                    if image_bytes:
                        records = self._process_frame(
                            image_bytes, camera_cfg["name"])
                        if records:
                            self.app.after(0, self.app.on_new_attendance,
                                           records)
                except Exception as e:
                    logger.error(
                        f"Error processing camera {camera_cfg['name']}: {e}")

            time.sleep(interval)

        logger.info("Attendance engine stopped")

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False


# ─── Main Application ───

class AttendanceApp(ctk.CTk if CTK else tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Law Minister's Office — Staff Attendance System")
        self.geometry("1280x800")
        self.minsize(1024, 700)

        if CTK:
            self.configure(fg_color=DARK_BG)

        db.init_db()
        self.engine = AttendanceDesktopEngine(self)
        self._build_ui()
        self._refresh_dashboard()
        self._start_status_updater()

    # ─── UI Builder ───

    def _build_ui(self):
        # Top bar
        self._build_header()

        # Main container
        self.main_frame = ctk.CTkFrame(self, fg_color=DARK_BG) if CTK else tk.Frame(self, bg=DARK_BG)
        self.main_frame.pack(fill="both", expand=True, padx=0, pady=0)

        # Sidebar nav
        self._build_sidebar()

        # Content area
        self.content = ctk.CTkFrame(self.main_frame, fg_color=DARK_BG) if CTK else tk.Frame(self.main_frame, bg=DARK_BG)
        self.content.pack(side="left", fill="both", expand=True)

        # Tab frames
        self.tabs = {}
        for tab_name in ["dashboard", "staff", "cameras", "attendance", "settings"]:
            frame = ctk.CTkFrame(self.content, fg_color=DARK_BG) if CTK else tk.Frame(self.content, bg=DARK_BG)
            self.tabs[tab_name] = frame

        self._build_dashboard_tab()
        self._build_staff_tab()
        self._build_cameras_tab()
        self._build_attendance_tab()
        self._build_settings_tab()

        self._show_tab("dashboard")

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=NAVY, height=60, corner_radius=0) if CTK else tk.Frame(self, bg=NAVY, height=60)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_lbl = ctk.CTkLabel(
            header, text="⚖  Law Minister's Office — Staff Attendance",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=GOLD,
        ) if CTK else tk.Label(header, text="Law Minister's Office — Staff Attendance", bg=NAVY, fg=GOLD, font=("Segoe UI", 16, "bold"))
        title_lbl.pack(side="left", padx=20, pady=15)

        # Engine control
        engine_frame = ctk.CTkFrame(header, fg_color=NAVY) if CTK else tk.Frame(header, bg=NAVY)
        engine_frame.pack(side="right", padx=20, pady=10)

        self.engine_dot = ctk.CTkLabel(engine_frame, text="●", text_color=DANGER, font=ctk.CTkFont(size=16)) if CTK else tk.Label(engine_frame, text="●", fg=DANGER, bg=NAVY, font=("Segoe UI", 14))
        self.engine_dot.pack(side="left", padx=(0, 5))

        self.engine_label = ctk.CTkLabel(engine_frame, text="Engine Stopped", text_color=TEXT_DIM, font=ctk.CTkFont(size=12)) if CTK else tk.Label(engine_frame, text="Engine Stopped", fg=TEXT_DIM, bg=NAVY, font=("Segoe UI", 10))
        self.engine_label.pack(side="left", padx=(0, 10))

        self.engine_btn = ctk.CTkButton(
            engine_frame, text="▶ Start", width=100,
            fg_color=SUCCESS, hover_color="#219a52",
            command=self._toggle_engine,
        ) if CTK else tk.Button(engine_frame, text="Start", bg=SUCCESS, fg="white", command=self._toggle_engine)
        self.engine_btn.pack(side="left")

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self.main_frame, fg_color=CARD_BG, width=200, corner_radius=0) if CTK else tk.Frame(self.main_frame, bg=CARD_BG, width=200)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        nav_items = [
            ("📊  Dashboard", "dashboard"),
            ("👤  Staff", "staff"),
            ("📷  Cameras", "cameras"),
            ("📋  Attendance", "attendance"),
            ("⚙  Settings", "settings"),
        ]

        self.nav_buttons = {}
        for label, tab_name in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w",
                fg_color="transparent", hover_color=ACCENT,
                text_color=TEXT, font=ctk.CTkFont(size=14),
                height=45, corner_radius=8,
                command=lambda t=tab_name: self._show_tab(t),
            ) if CTK else tk.Button(sidebar, text=label, bg=CARD_BG, fg=TEXT, anchor="w", command=lambda t=tab_name: self._show_tab(t))
            btn.pack(fill="x", padx=10, pady=3)
            self.nav_buttons[tab_name] = btn

    def _show_tab(self, tab_name: str):
        for name, frame in self.tabs.items():
            frame.pack_forget()
        self.tabs[tab_name].pack(fill="both", expand=True, padx=20, pady=15)

        for name, btn in self.nav_buttons.items():
            if CTK:
                btn.configure(fg_color=ACCENT if name == tab_name else "transparent")

        if tab_name == "dashboard":
            self._refresh_dashboard()
        elif tab_name == "staff":
            self._refresh_staff_list()
        elif tab_name == "cameras":
            self._refresh_cameras()
        elif tab_name == "attendance":
            self._refresh_attendance_log()
        elif tab_name == "settings":
            self._load_settings()

    # ═══════════════════════════════════════
    # Dashboard Tab
    # ═══════════════════════════════════════

    def _build_dashboard_tab(self):
        tab = self.tabs["dashboard"]

        title = ctk.CTkLabel(tab, text="Dashboard", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT) if CTK else tk.Label(tab, text="Dashboard", font=("Segoe UI", 20, "bold"), fg=TEXT, bg=DARK_BG)
        title.pack(anchor="w", pady=(0, 15))

        # Stats cards row
        stats_frame = ctk.CTkFrame(tab, fg_color="transparent") if CTK else tk.Frame(tab, bg=DARK_BG)
        stats_frame.pack(fill="x", pady=(0, 15))

        self.stat_labels = {}
        stats = [
            ("Total Staff", "total", BLUE),
            ("Present", "present", SUCCESS),
            ("Absent", "absent", DANGER),
            ("Attendance %", "pct", GOLD),
        ]
        for label, key, color in stats:
            card = ctk.CTkFrame(stats_frame, fg_color=CARD_BG, corner_radius=12, height=100) if CTK else tk.Frame(stats_frame, bg=CARD_BG, height=100)
            card.pack(side="left", fill="both", expand=True, padx=5)
            card.pack_propagate(False)

            lbl = ctk.CTkLabel(card, text=label, text_color=TEXT_DIM, font=ctk.CTkFont(size=12)) if CTK else tk.Label(card, text=label, fg=TEXT_DIM, bg=CARD_BG, font=("Segoe UI", 10))
            lbl.pack(pady=(15, 2))

            val = ctk.CTkLabel(card, text="0", text_color=color, font=ctk.CTkFont(size=32, weight="bold")) if CTK else tk.Label(card, text="0", fg=color, bg=CARD_BG, font=("Segoe UI", 28, "bold"))
            val.pack()
            self.stat_labels[key] = val

        # Today's attendance table
        table_label = ctk.CTkLabel(tab, text="Today's Attendance", font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT) if CTK else tk.Label(tab, text="Today's Attendance", font=("Segoe UI", 14, "bold"), fg=TEXT, bg=DARK_BG)
        table_label.pack(anchor="w", pady=(10, 5))

        tree_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=8) if CTK else tk.Frame(tab, bg=CARD_BG)
        tree_frame.pack(fill="both", expand=True)

        cols = ("staff_id", "name", "status", "time_in", "confidence")
        self.dash_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=12)
        self.dash_tree.heading("staff_id", text="Staff ID")
        self.dash_tree.heading("name", text="Name")
        self.dash_tree.heading("status", text="Status")
        self.dash_tree.heading("time_in", text="Time In")
        self.dash_tree.heading("confidence", text="Confidence")
        self.dash_tree.column("staff_id", width=100)
        self.dash_tree.column("name", width=200)
        self.dash_tree.column("status", width=100)
        self.dash_tree.column("time_in", width=120)
        self.dash_tree.column("confidence", width=100)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.dash_tree.yview)
        self.dash_tree.configure(yscrollcommand=scrollbar.set)
        self.dash_tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y", pady=5)

        # Manual check-in section
        checkin_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=8) if CTK else tk.Frame(tab, bg=CARD_BG)
        checkin_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkLabel(checkin_frame, text="Manual Check-in", font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT).pack(side="left", padx=15, pady=10) if CTK else tk.Label(checkin_frame, text="Manual Check-in", font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD_BG).pack(side="left", padx=15, pady=10)

        self.checkin_result = ctk.CTkLabel(checkin_frame, text="", text_color=TEXT_DIM, font=ctk.CTkFont(size=12)) if CTK else tk.Label(checkin_frame, text="", fg=TEXT_DIM, bg=CARD_BG, font=("Segoe UI", 10))
        self.checkin_result.pack(side="left", padx=10)

        btn = ctk.CTkButton(
            checkin_frame, text="📁 Upload Photo", width=140,
            fg_color=BLUE, hover_color="#2980b9",
            command=self._manual_checkin,
        ) if CTK else tk.Button(checkin_frame, text="Upload Photo", bg=BLUE, fg="white", command=self._manual_checkin)
        btn.pack(side="right", padx=15, pady=10)

    def _refresh_dashboard(self):
        summary = db.get_attendance_summary()
        self.stat_labels["total"].configure(text=str(summary["total_staff"]))
        self.stat_labels["present"].configure(text=str(summary["present"]))
        self.stat_labels["absent"].configure(text=str(summary["absent"]))
        self.stat_labels["pct"].configure(text=f"{summary['attendance_pct']}%")

        self.dash_tree.delete(*self.dash_tree.get_children())
        all_staff = db.get_all_staff()
        records = db.get_attendance()
        present_ids = {r["staff_id"] for r in records}

        for staff in all_staff:
            sid = staff["staff_id"]
            record = next((r for r in records if r["staff_id"] == sid), None)
            status = "Present" if sid in present_ids else "Absent"
            time_in = record["logged_at"].split(" ")[-1][:5] if record else ""
            conf = f"{record['confidence']:.1%}" if record else ""
            tag = "present" if status == "Present" else "absent"
            self.dash_tree.insert("", "end", values=(sid, staff["name"], status, time_in, conf), tags=(tag,))

        self.dash_tree.tag_configure("present", foreground=SUCCESS)
        self.dash_tree.tag_configure("absent", foreground=DANGER)

    def _manual_checkin(self):
        filepath = filedialog.askopenfilename(
            title="Select Photo for Check-in",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp")],
        )
        if not filepath:
            return

        self.checkin_result.configure(text="Processing...")
        self.update()

        def process():
            with open(filepath, "rb") as f:
                image_bytes = f.read()

            cfg = load_config()
            threshold = cfg.get("recognition_threshold", 0.45)
            enhanced = face_engine.preprocess_image(image_bytes)
            detections = face_engine.detect_and_encode(enhanced)

            if not detections:
                self.after(0, lambda: self.checkin_result.configure(
                    text="No face detected", text_color=DANGER))
                return

            results = []
            matched = []
            for embedding, cropped_face, bbox in detections:
                match = face_engine.match_face(embedding, threshold=threshold)
                if match:
                    staff_id, name, confidence = match
                    ts = int(time.time())
                    snap_path = ATTENDANCE_SNAPSHOTS_DIR / f"{staff_id}_{ts}.jpg"
                    with open(snap_path, "wb") as f:
                        f.write(cropped_face)
                    db.log_attendance(
                        staff_id=staff_id, name=name,
                        confidence=confidence,
                        snapshot_path=str(snap_path),
                        camera_source="manual",
                    )
                    results.append(f"{name} ({confidence:.1%})")
                    matched.append((staff_id, name, confidence))

            if results:
                msg = "Matched: " + ", ".join(results)
                self.after(0, lambda: self.checkin_result.configure(
                    text=msg, text_color=SUCCESS))
                self.after(0, self._refresh_dashboard)
                for staff_id, name, confidence in matched:
                    wa.notify_checkin(
                        cfg, staff_name=name, staff_id=staff_id,
                        confidence=confidence, camera="manual",
                    )
            else:
                self.after(0, lambda: self.checkin_result.configure(
                    text="No registered face matched", text_color=WARNING))

        threading.Thread(target=process, daemon=True).start()

    # ═══════════════════════════════════════
    # Staff Management Tab
    # ═══════════════════════════════════════

    def _build_staff_tab(self):
        tab = self.tabs["staff"]

        header = ctk.CTkFrame(tab, fg_color="transparent") if CTK else tk.Frame(tab, bg=DARK_BG)
        header.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(header, text="Staff Management", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(side="left") if CTK else tk.Label(header, text="Staff Management", font=("Segoe UI", 20, "bold"), fg=TEXT, bg=DARK_BG).pack(side="left")

        ctk.CTkButton(
            header, text="+ Add Staff", width=120,
            fg_color=SUCCESS, hover_color="#219a52",
            command=self._show_add_staff_dialog,
        ).pack(side="right") if CTK else tk.Button(header, text="+ Add Staff", bg=SUCCESS, fg="white", command=self._show_add_staff_dialog).pack(side="right")

        # Staff table
        tree_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=8) if CTK else tk.Frame(tab, bg=CARD_BG)
        tree_frame.pack(fill="both", expand=True)

        cols = ("staff_id", "name", "designation", "department", "phone", "faces", "status")
        self.staff_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=18)
        self.staff_tree.heading("staff_id", text="Staff ID")
        self.staff_tree.heading("name", text="Name")
        self.staff_tree.heading("designation", text="Designation")
        self.staff_tree.heading("department", text="Department")
        self.staff_tree.heading("phone", text="Phone")
        self.staff_tree.heading("faces", text="Faces")
        self.staff_tree.heading("status", text="Status")
        self.staff_tree.column("staff_id", width=90)
        self.staff_tree.column("name", width=180)
        self.staff_tree.column("designation", width=150)
        self.staff_tree.column("department", width=150)
        self.staff_tree.column("phone", width=120)
        self.staff_tree.column("faces", width=60)
        self.staff_tree.column("status", width=80)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.staff_tree.yview)
        self.staff_tree.configure(yscrollcommand=scrollbar.set)
        self.staff_tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y", pady=5)

        # Action buttons
        action_frame = ctk.CTkFrame(tab, fg_color="transparent") if CTK else tk.Frame(tab, bg=DARK_BG)
        action_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(action_frame, text="📸 Register Face", width=140, fg_color=BLUE, hover_color="#2980b9", command=self._register_face_dialog).pack(side="left", padx=5) if CTK else None
        ctk.CTkButton(action_frame, text="🗑 Delete Staff", width=130, fg_color=DANGER, hover_color="#c0392b", command=self._delete_selected_staff).pack(side="left", padx=5) if CTK else None
        ctk.CTkButton(action_frame, text="🔄 Refresh", width=100, fg_color=ACCENT, hover_color="#0a2948", command=self._refresh_staff_list).pack(side="right", padx=5) if CTK else None

    def _refresh_staff_list(self):
        self.staff_tree.delete(*self.staff_tree.get_children())
        staff = db.get_all_staff(active_only=False)
        for s in staff:
            encodings = db.get_face_encodings(s["staff_id"])
            face_count = len(encodings)
            status = "Active" if s["active"] else "Inactive"
            self.staff_tree.insert("", "end", values=(
                s["staff_id"], s["name"], s["designation"],
                s["department"], s["phone"], face_count, status,
            ))

    def _show_add_staff_dialog(self):
        dialog = ctk.CTkToplevel(self) if CTK else tk.Toplevel(self)
        dialog.title("Add New Staff Member")
        dialog.geometry("500x550")
        dialog.transient(self)
        dialog.grab_set()
        if CTK:
            dialog.configure(fg_color=DARK_BG)

        fields = {}
        field_defs = [
            ("Staff ID *", "staff_id"),
            ("Full Name *", "name"),
            ("Designation", "designation"),
            ("Department", "department"),
            ("Phone", "phone"),
            ("Email", "email"),
        ]

        for label_text, key in field_defs:
            frame = ctk.CTkFrame(dialog, fg_color="transparent") if CTK else tk.Frame(dialog, bg=DARK_BG)
            frame.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(frame, text=label_text, text_color=TEXT, font=ctk.CTkFont(size=13), width=120, anchor="w").pack(side="left") if CTK else tk.Label(frame, text=label_text, fg=TEXT, bg=DARK_BG, font=("Segoe UI", 11), width=15, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(frame, width=300, fg_color=CARD_BG, text_color=TEXT, border_color=ACCENT) if CTK else tk.Entry(frame, bg=CARD_BG, fg=TEXT, width=35)
            entry.pack(side="left", fill="x", expand=True)
            fields[key] = entry

        # Face photo
        photo_frame = ctk.CTkFrame(dialog, fg_color="transparent") if CTK else tk.Frame(dialog, bg=DARK_BG)
        photo_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(photo_frame, text="Face Photo", text_color=TEXT, font=ctk.CTkFont(size=13), width=120, anchor="w").pack(side="left") if CTK else tk.Label(photo_frame, text="Face Photo", fg=TEXT, bg=DARK_BG, font=("Segoe UI", 11), width=15, anchor="w").pack(side="left")

        photo_path_var = tk.StringVar(value="No file selected")
        photo_label = ctk.CTkLabel(photo_frame, textvariable=photo_path_var, text_color=TEXT_DIM, font=ctk.CTkFont(size=11)) if CTK else tk.Label(photo_frame, textvariable=photo_path_var, fg=TEXT_DIM, bg=DARK_BG, font=("Segoe UI", 9))
        photo_label.pack(side="left", padx=10)

        selected_photo = [None]

        def pick_photo():
            path = filedialog.askopenfilename(
                title="Select Face Photo",
                filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp")],
            )
            if path:
                selected_photo[0] = path
                photo_path_var.set(Path(path).name)

        ctk.CTkButton(photo_frame, text="Browse", width=80, fg_color=ACCENT, command=pick_photo).pack(side="right") if CTK else tk.Button(photo_frame, text="Browse", bg=ACCENT, fg="white", command=pick_photo).pack(side="right")

        # Save button
        def save_staff():
            staff_id = fields["staff_id"].get().strip()
            name = fields["name"].get().strip()
            if not staff_id or not name:
                messagebox.showerror("Error", "Staff ID and Name are required")
                return
            if db.get_staff(staff_id):
                messagebox.showerror("Error", f"Staff ID {staff_id} already exists")
                return

            db.add_staff(
                staff_id=staff_id,
                name=name,
                designation=fields["designation"].get().strip(),
                department=fields["department"].get().strip(),
                phone=fields["phone"].get().strip(),
                email=fields["email"].get().strip(),
            )

            if selected_photo[0]:
                with open(selected_photo[0], "rb") as f:
                    image_bytes = f.read()
                result = face_engine.register_staff_face(staff_id, image_bytes, "front")
                if not result["success"]:
                    messagebox.showwarning("Warning", f"Staff added but face registration failed: {result['error']}")
                else:
                    logger.info(f"Face registered for {staff_id}")

            dialog.destroy()
            self._refresh_staff_list()
            messagebox.showinfo("Success", f"Staff member {name} added successfully")

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent") if CTK else tk.Frame(dialog, bg=DARK_BG)
        btn_frame.pack(fill="x", padx=20, pady=20)
        ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color=ACCENT, command=dialog.destroy).pack(side="left") if CTK else tk.Button(btn_frame, text="Cancel", bg=ACCENT, fg="white", command=dialog.destroy).pack(side="left")
        ctk.CTkButton(btn_frame, text="✓ Add Staff", width=130, fg_color=SUCCESS, hover_color="#219a52", command=save_staff).pack(side="right") if CTK else tk.Button(btn_frame, text="Add Staff", bg=SUCCESS, fg="white", command=save_staff).pack(side="right")

    def _register_face_dialog(self):
        sel = self.staff_tree.selection()
        if not sel:
            messagebox.showinfo("Select Staff", "Please select a staff member first")
            return

        values = self.staff_tree.item(sel[0])["values"]
        staff_id = str(values[0])
        name = str(values[1])

        filepath = filedialog.askopenfilename(
            title=f"Select Face Photo for {name}",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp")],
        )
        if not filepath:
            return

        def register():
            with open(filepath, "rb") as f:
                image_bytes = f.read()
            result = face_engine.register_staff_face(staff_id, image_bytes, "front")
            if result["success"]:
                self.after(0, lambda: messagebox.showinfo("Success", f"Face registered for {name}"))
                self.after(0, self._refresh_staff_list)
            else:
                self.after(0, lambda: messagebox.showerror("Error", result["error"]))

        threading.Thread(target=register, daemon=True).start()

    def _delete_selected_staff(self):
        sel = self.staff_tree.selection()
        if not sel:
            messagebox.showinfo("Select Staff", "Please select a staff member first")
            return

        values = self.staff_tree.item(sel[0])["values"]
        staff_id = str(values[0])
        name = str(values[1])

        if not messagebox.askyesno("Confirm Delete", f"Delete {name} ({staff_id})?\nThis will also remove all face encodings."):
            return

        db.delete_staff(staff_id)
        self._refresh_staff_list()

    # ═══════════════════════════════════════
    # Cameras Tab
    # ═══════════════════════════════════════

    def _build_cameras_tab(self):
        tab = self.tabs["cameras"]

        header = ctk.CTkFrame(tab, fg_color="transparent") if CTK else tk.Frame(tab, bg=DARK_BG)
        header.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(header, text="Camera Configuration", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(side="left") if CTK else tk.Label(header, text="Camera Configuration", font=("Segoe UI", 20, "bold"), fg=TEXT, bg=DARK_BG).pack(side="left")

        ctk.CTkButton(header, text="+ Add Camera", width=130, fg_color=SUCCESS, hover_color="#219a52", command=self._show_add_camera_dialog).pack(side="right") if CTK else tk.Button(header, text="+ Add Camera", bg=SUCCESS, fg="white", command=self._show_add_camera_dialog).pack(side="right")

        tree_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=8) if CTK else tk.Frame(tab, bg=CARD_BG)
        tree_frame.pack(fill="both", expand=True)

        cols = ("id", "name", "type", "ip_url", "status")
        self.cam_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=10)
        self.cam_tree.heading("id", text="ID")
        self.cam_tree.heading("name", text="Name")
        self.cam_tree.heading("type", text="Type")
        self.cam_tree.heading("ip_url", text="IP / URL")
        self.cam_tree.heading("status", text="Status")
        self.cam_tree.column("id", width=50)
        self.cam_tree.column("name", width=200)
        self.cam_tree.column("type", width=120)
        self.cam_tree.column("ip_url", width=300)
        self.cam_tree.column("status", width=100)
        self.cam_tree.pack(fill="both", expand=True, padx=5, pady=5)

        action_frame = ctk.CTkFrame(tab, fg_color="transparent") if CTK else tk.Frame(tab, bg=DARK_BG)
        action_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(action_frame, text="🔍 Test Camera", width=130, fg_color=BLUE, hover_color="#2980b9", command=self._test_camera).pack(side="left", padx=5) if CTK else None
        ctk.CTkButton(action_frame, text="🗑 Delete Camera", width=130, fg_color=DANGER, hover_color="#c0392b", command=self._delete_camera).pack(side="left", padx=5) if CTK else None

    def _refresh_cameras(self):
        self.cam_tree.delete(*self.cam_tree.get_children())
        cameras = db.get_cameras(active_only=False)
        for c in cameras:
            ip_url = c.get("source_url") or c.get("ip", "")
            status = "Active" if c["active"] else "Inactive"
            self.cam_tree.insert("", "end", values=(
                c["id"], c["name"], c["source_type"], ip_url, status,
            ))

    def _show_add_camera_dialog(self):
        dialog = ctk.CTkToplevel(self) if CTK else tk.Toplevel(self)
        dialog.title("Add Camera")
        dialog.geometry("500x480")
        dialog.transient(self)
        dialog.grab_set()
        if CTK:
            dialog.configure(fg_color=DARK_BG)

        fields = {}
        field_defs = [
            ("Camera Name *", "name"),
            ("IP Address", "ip"),
            ("Port", "port"),
            ("Username", "username"),
            ("Password", "password"),
            ("RTSP URL", "source_url"),
            ("Channel", "channel"),
            ("Description", "description"),
        ]

        # Source type selector
        type_frame = ctk.CTkFrame(dialog, fg_color="transparent") if CTK else tk.Frame(dialog, bg=DARK_BG)
        type_frame.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(type_frame, text="Source Type *", text_color=TEXT, font=ctk.CTkFont(size=13), width=120, anchor="w").pack(side="left") if CTK else None

        type_var = tk.StringVar(value="hikvision")
        type_menu = ctk.CTkOptionMenu(type_frame, variable=type_var, values=["hikvision", "rtsp", "webcam", "url"], fg_color=CARD_BG, button_color=ACCENT, width=200) if CTK else ttk.Combobox(type_frame, textvariable=type_var, values=["hikvision", "rtsp", "webcam", "url"])
        type_menu.pack(side="left", padx=10)

        for label_text, key in field_defs:
            frame = ctk.CTkFrame(dialog, fg_color="transparent") if CTK else tk.Frame(dialog, bg=DARK_BG)
            frame.pack(fill="x", padx=20, pady=4)
            ctk.CTkLabel(frame, text=label_text, text_color=TEXT, font=ctk.CTkFont(size=13), width=120, anchor="w").pack(side="left") if CTK else tk.Label(frame, text=label_text, fg=TEXT, bg=DARK_BG, width=15, anchor="w").pack(side="left")
            show = "*" if key == "password" else ""
            entry = ctk.CTkEntry(frame, width=300, fg_color=CARD_BG, text_color=TEXT, border_color=ACCENT, show=show) if CTK else tk.Entry(frame, bg=CARD_BG, fg=TEXT, width=35, show=show)
            entry.pack(side="left", fill="x", expand=True)
            if key == "port":
                entry.insert(0, "80")
            elif key == "channel":
                entry.insert(0, "1")
            fields[key] = entry

        def save_camera():
            name = fields["name"].get().strip()
            if not name:
                messagebox.showerror("Error", "Camera name is required")
                return

            db.add_camera(
                name=name,
                source_type=type_var.get(),
                source_url=fields["source_url"].get().strip(),
                ip=fields["ip"].get().strip(),
                port=int(fields["port"].get() or 80),
                username=fields["username"].get().strip(),
                password=fields["password"].get().strip(),
                channel=int(fields["channel"].get() or 1),
                description=fields["description"].get().strip(),
            )
            dialog.destroy()
            self._refresh_cameras()
            messagebox.showinfo("Success", f"Camera '{name}' added")

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent") if CTK else tk.Frame(dialog, bg=DARK_BG)
        btn_frame.pack(fill="x", padx=20, pady=15)
        ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color=ACCENT, command=dialog.destroy).pack(side="left") if CTK else None
        ctk.CTkButton(btn_frame, text="✓ Add Camera", width=130, fg_color=SUCCESS, hover_color="#219a52", command=save_camera).pack(side="right") if CTK else None

    def _test_camera(self):
        sel = self.cam_tree.selection()
        if not sel:
            messagebox.showinfo("Select Camera", "Please select a camera first")
            return

        values = self.cam_tree.item(sel[0])["values"]
        cam_id = values[0]
        cameras = db.get_cameras(active_only=False)
        cam_cfg = next((c for c in cameras if c["id"] == cam_id), None)
        if not cam_cfg:
            return

        def test():
            frame = cam.capture_from_camera(cam_cfg)
            if frame:
                self.after(0, lambda: messagebox.showinfo(
                    "Camera Test",
                    f"Camera '{cam_cfg['name']}' is working!\nCaptured frame: {len(frame):,} bytes"))
            else:
                self.after(0, lambda: messagebox.showerror(
                    "Camera Test",
                    f"Failed to capture from '{cam_cfg['name']}'.\nCheck connection settings."))

        threading.Thread(target=test, daemon=True).start()

    def _delete_camera(self):
        sel = self.cam_tree.selection()
        if not sel:
            messagebox.showinfo("Select Camera", "Please select a camera first")
            return
        values = self.cam_tree.item(sel[0])["values"]
        cam_id = values[0]
        name = values[1]
        if messagebox.askyesno("Confirm", f"Delete camera '{name}'?"):
            db.delete_camera(cam_id)
            self._refresh_cameras()

    # ═══════════════════════════════════════
    # Attendance Log Tab
    # ═══════════════════════════════════════

    def _build_attendance_tab(self):
        tab = self.tabs["attendance"]

        header = ctk.CTkFrame(tab, fg_color="transparent") if CTK else tk.Frame(tab, bg=DARK_BG)
        header.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(header, text="Attendance Log", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(side="left") if CTK else tk.Label(header, text="Attendance Log", font=("Segoe UI", 20, "bold"), fg=TEXT, bg=DARK_BG).pack(side="left")

        # Date filter
        filter_frame = ctk.CTkFrame(header, fg_color="transparent") if CTK else tk.Frame(header, bg=DARK_BG)
        filter_frame.pack(side="right")

        ctk.CTkLabel(filter_frame, text="Date:", text_color=TEXT_DIM).pack(side="left", padx=5) if CTK else None
        self.att_date_var = tk.StringVar(value=str(date.today()))
        date_entry = ctk.CTkEntry(filter_frame, textvariable=self.att_date_var, width=120, fg_color=CARD_BG, text_color=TEXT, border_color=ACCENT) if CTK else tk.Entry(filter_frame, textvariable=self.att_date_var, bg=CARD_BG, fg=TEXT, width=12)
        date_entry.pack(side="left", padx=5)

        ctk.CTkButton(filter_frame, text="🔍 Filter", width=80, fg_color=BLUE, command=self._refresh_attendance_log).pack(side="left", padx=5) if CTK else None
        ctk.CTkButton(filter_frame, text="📥 Export CSV", width=110, fg_color=GOLD, text_color=NAVY, hover_color="#b8943f", command=self._export_csv).pack(side="left", padx=5) if CTK else None

        tree_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=8) if CTK else tk.Frame(tab, bg=CARD_BG)
        tree_frame.pack(fill="both", expand=True)

        cols = ("id", "staff_id", "name", "status", "confidence", "camera", "time")
        self.att_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=20)
        self.att_tree.heading("id", text="#")
        self.att_tree.heading("staff_id", text="Staff ID")
        self.att_tree.heading("name", text="Name")
        self.att_tree.heading("status", text="Status")
        self.att_tree.heading("confidence", text="Confidence")
        self.att_tree.heading("camera", text="Camera")
        self.att_tree.heading("time", text="Time")
        self.att_tree.column("id", width=50)
        self.att_tree.column("staff_id", width=100)
        self.att_tree.column("name", width=200)
        self.att_tree.column("status", width=80)
        self.att_tree.column("confidence", width=100)
        self.att_tree.column("camera", width=150)
        self.att_tree.column("time", width=150)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.att_tree.yview)
        self.att_tree.configure(yscrollcommand=scrollbar.set)
        self.att_tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y", pady=5)

    def _refresh_attendance_log(self):
        date_str = self.att_date_var.get().strip()
        self.att_tree.delete(*self.att_tree.get_children())
        records = db.get_attendance(date_str if date_str != str(date.today()) else None)
        for r in records:
            self.att_tree.insert("", "end", values=(
                r["id"], r["staff_id"], r["name"], r["status"],
                f"{r['confidence']:.1%}", r["camera_source"],
                r["logged_at"],
            ))

    def _export_csv(self):
        date_str = self.att_date_var.get().strip()
        records = db.get_attendance(date_str if date_str != str(date.today()) else None)
        all_staff = db.get_all_staff()
        present_ids = {r["staff_id"] for r in records}

        filepath = filedialog.asksaveasfilename(
            title="Export Attendance CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"attendance_{date_str}.csv",
        )
        if not filepath:
            return

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Staff ID", "Name", "Designation", "Department",
                             "Status", "Time In", "Confidence"])
            for staff in all_staff:
                sid = staff["staff_id"]
                record = next((r for r in records if r["staff_id"] == sid), None)
                status = "Present" if sid in present_ids else "Absent"
                time_in = record["logged_at"] if record else ""
                conf = f"{record['confidence']:.3f}" if record else ""
                writer.writerow([sid, staff["name"], staff["designation"],
                                 staff["department"], status, time_in, conf])

        messagebox.showinfo("Exported", f"Attendance exported to:\n{filepath}")

    # ═══════════════════════════════════════
    # Settings Tab
    # ═══════════════════════════════════════

    def _build_settings_tab(self):
        tab = self.tabs["settings"]

        ctk.CTkLabel(tab, text="Settings", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(anchor="w", pady=(0, 15)) if CTK else tk.Label(tab, text="Settings", font=("Segoe UI", 20, "bold"), fg=TEXT, bg=DARK_BG).pack(anchor="w", pady=(0, 15))

        settings_card = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=12) if CTK else tk.Frame(tab, bg=CARD_BG)
        settings_card.pack(fill="x")

        self.setting_vars = {}
        setting_defs = [
            ("Office Name", "office_name", "text"),
            ("Attendance Start Hour (0-23)", "attendance_start_hour", "int"),
            ("Attendance Start Minute", "attendance_start_minute", "int"),
            ("Attendance End Hour (0-23)", "attendance_end_hour", "int"),
            ("Attendance End Minute", "attendance_end_minute", "int"),
            ("Recognition Threshold (0.2-0.9)", "recognition_threshold", "float"),
            ("Cooldown Seconds", "cooldown_seconds", "int"),
            ("Snapshot Interval Seconds", "snapshot_interval_seconds", "int"),
        ]

        for label_text, key, dtype in setting_defs:
            row = ctk.CTkFrame(settings_card, fg_color="transparent") if CTK else tk.Frame(settings_card, bg=CARD_BG)
            row.pack(fill="x", padx=20, pady=6)
            ctk.CTkLabel(row, text=label_text, text_color=TEXT, font=ctk.CTkFont(size=13), width=260, anchor="w").pack(side="left") if CTK else tk.Label(row, text=label_text, fg=TEXT, bg=CARD_BG, font=("Segoe UI", 11), width=30, anchor="w").pack(side="left")
            var = tk.StringVar()
            entry = ctk.CTkEntry(row, textvariable=var, width=200, fg_color=DARK_BG, text_color=TEXT, border_color=ACCENT) if CTK else tk.Entry(row, textvariable=var, bg=DARK_BG, fg=TEXT, width=25)
            entry.pack(side="left")
            self.setting_vars[key] = (var, dtype)

        # ─── WhatsApp Notification Settings ───
        wa_label = ctk.CTkLabel(tab, text="WhatsApp Notifications", font=ctk.CTkFont(size=18, weight="bold"), text_color=GOLD) if CTK else tk.Label(tab, text="WhatsApp Notifications", font=("Segoe UI", 16, "bold"), fg=GOLD, bg=DARK_BG)
        wa_label.pack(anchor="w", pady=(20, 10))

        wa_card = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=12) if CTK else tk.Frame(tab, bg=CARD_BG)
        wa_card.pack(fill="x")

        # Enable/Disable toggle
        wa_toggle_row = ctk.CTkFrame(wa_card, fg_color="transparent") if CTK else tk.Frame(wa_card, bg=CARD_BG)
        wa_toggle_row.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(wa_toggle_row, text="Enable WhatsApp Alerts", text_color=TEXT, font=ctk.CTkFont(size=13), width=260, anchor="w").pack(side="left") if CTK else tk.Label(wa_toggle_row, text="Enable WhatsApp Alerts", fg=TEXT, bg=CARD_BG, font=("Segoe UI", 11), width=30, anchor="w").pack(side="left")
        self.wa_enabled_var = tk.BooleanVar(value=False)
        if CTK:
            self.wa_toggle = ctk.CTkSwitch(wa_toggle_row, text="", variable=self.wa_enabled_var, onvalue=True, offvalue=False, progress_color=SUCCESS)
            self.wa_toggle.pack(side="left")
        else:
            tk.Checkbutton(wa_toggle_row, variable=self.wa_enabled_var, bg=CARD_BG, fg=TEXT, selectcolor=DARK_BG).pack(side="left")

        # Recipient number
        wa_recip_row = ctk.CTkFrame(wa_card, fg_color="transparent") if CTK else tk.Frame(wa_card, bg=CARD_BG)
        wa_recip_row.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(wa_recip_row, text="Recipient Phone Number", text_color=TEXT, font=ctk.CTkFont(size=13), width=260, anchor="w").pack(side="left") if CTK else tk.Label(wa_recip_row, text="Recipient Phone Number", fg=TEXT, bg=CARD_BG, font=("Segoe UI", 11), width=30, anchor="w").pack(side="left")
        self.wa_recipient_var = tk.StringVar()
        wa_entry = ctk.CTkEntry(wa_recip_row, textvariable=self.wa_recipient_var, width=200, fg_color=DARK_BG, text_color=TEXT, border_color=ACCENT, placeholder_text="+91XXXXXXXXXX") if CTK else tk.Entry(wa_recip_row, textvariable=self.wa_recipient_var, bg=DARK_BG, fg=TEXT, width=25)
        wa_entry.pack(side="left")

        # Phone ID (pre-filled, rarely changed)
        wa_pid_row = ctk.CTkFrame(wa_card, fg_color="transparent") if CTK else tk.Frame(wa_card, bg=CARD_BG)
        wa_pid_row.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(wa_pid_row, text="WhatsApp Phone ID", text_color=TEXT_DIM, font=ctk.CTkFont(size=13), width=260, anchor="w").pack(side="left") if CTK else tk.Label(wa_pid_row, text="WhatsApp Phone ID", fg=TEXT_DIM, bg=CARD_BG, font=("Segoe UI", 11), width=30, anchor="w").pack(side="left")
        self.wa_phone_id_var = tk.StringVar()
        wa_pid_entry = ctk.CTkEntry(wa_pid_row, textvariable=self.wa_phone_id_var, width=200, fg_color=DARK_BG, text_color=TEXT_DIM, border_color=ACCENT) if CTK else tk.Entry(wa_pid_row, textvariable=self.wa_phone_id_var, bg=DARK_BG, fg=TEXT_DIM, width=25)
        wa_pid_entry.pack(side="left")

        # Test button
        wa_test_row = ctk.CTkFrame(wa_card, fg_color="transparent") if CTK else tk.Frame(wa_card, bg=CARD_BG)
        wa_test_row.pack(fill="x", padx=20, pady=10)
        ctk.CTkButton(wa_test_row, text="Send Test Message", width=180, fg_color=BLUE, hover_color="#2980b9", command=self._test_whatsapp).pack(side="left") if CTK else tk.Button(wa_test_row, text="Send Test Message", bg=BLUE, fg="white", command=self._test_whatsapp).pack(side="left")
        self.wa_status_label = ctk.CTkLabel(wa_test_row, text="", font=ctk.CTkFont(size=12), text_color=TEXT_DIM) if CTK else tk.Label(wa_test_row, text="", fg=TEXT_DIM, bg=CARD_BG, font=("Segoe UI", 10))
        self.wa_status_label.pack(side="left", padx=15)

        btn_frame = ctk.CTkFrame(tab, fg_color="transparent") if CTK else tk.Frame(tab, bg=DARK_BG)
        btn_frame.pack(fill="x", pady=20)
        ctk.CTkButton(btn_frame, text="Save Settings", width=150, fg_color=SUCCESS, hover_color="#219a52", command=self._save_settings).pack(side="left", padx=5) if CTK else tk.Button(btn_frame, text="Save Settings", bg=SUCCESS, fg="white", command=self._save_settings).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Reset to Defaults", width=150, fg_color=ACCENT, command=self._reset_settings).pack(side="left", padx=5) if CTK else None

    def _load_settings(self):
        cfg = load_config()
        for key, (var, dtype) in self.setting_vars.items():
            var.set(str(cfg.get(key, "")))
        self.wa_enabled_var.set(cfg.get("whatsapp_enabled", False))
        self.wa_recipient_var.set(cfg.get("whatsapp_recipient", ""))
        self.wa_phone_id_var.set(cfg.get("whatsapp_phone_id", "902332186299839"))

    def _save_settings(self):
        cfg = load_config()
        for key, (var, dtype) in self.setting_vars.items():
            val = var.get().strip()
            if dtype == "int":
                try:
                    cfg[key] = int(val)
                except ValueError:
                    pass
            elif dtype == "float":
                try:
                    cfg[key] = float(val)
                except ValueError:
                    pass
            else:
                cfg[key] = val
        cfg["whatsapp_enabled"] = self.wa_enabled_var.get()
        cfg["whatsapp_recipient"] = self.wa_recipient_var.get().strip()
        cfg["whatsapp_phone_id"] = self.wa_phone_id_var.get().strip()
        save_config(cfg)
        messagebox.showinfo("Saved", "Settings saved successfully")

    def _test_whatsapp(self):
        """Send a test WhatsApp message to verify configuration."""
        recipient = self.wa_recipient_var.get().strip()
        phone_id = self.wa_phone_id_var.get().strip()
        if not recipient:
            self.wa_status_label.configure(text="Enter recipient number first", text_color=DANGER)
            return
        cfg = load_config()
        cfg["whatsapp_enabled"] = True
        cfg["whatsapp_recipient"] = recipient
        cfg["whatsapp_phone_id"] = phone_id
        self.wa_status_label.configure(text="Sending...", text_color=WARNING)
        self.update()

        office = cfg.get("office_name", "Law Minister's Office")
        body = (
            f"*{office} — Test Message*\n\n"
            f"WhatsApp notifications are configured and working.\n"
            f"Check-in alerts will be sent to this number.\n\n"
            f"_LEGIT COMMUNISYS — Automated Notification_"
        )
        ok = wa.send_text_message(cfg, recipient, body)
        if ok:
            self.wa_status_label.configure(text="Test message sent!", text_color=SUCCESS)
        else:
            self.wa_status_label.configure(text="Failed — check token & number", text_color=DANGER)

    def _reset_settings(self):
        from backend.config import DEFAULT_CONFIG
        save_config(dict(DEFAULT_CONFIG))
        self._load_settings()
        messagebox.showinfo("Reset", "Settings reset to defaults")

    # ─── Engine Control ───

    def _toggle_engine(self):
        if self.engine.running:
            self.engine.stop()
            if CTK:
                self.engine_btn.configure(text="▶ Start", fg_color=SUCCESS, hover_color="#219a52")
                self.engine_dot.configure(text_color=DANGER)
                self.engine_label.configure(text="Engine Stopped")
        else:
            self.engine.start()
            if CTK:
                self.engine_btn.configure(text="■ Stop", fg_color=DANGER, hover_color="#c0392b")
                self.engine_dot.configure(text_color=SUCCESS)
                self.engine_label.configure(text="Engine Running")

    def _start_status_updater(self):
        def update():
            if self.engine.running:
                stats = self.engine.stats
                frames = stats.get("frames_processed", 0)
                matches = stats.get("matches_found", 0)
                if CTK:
                    self.engine_label.configure(
                        text=f"Running — {frames} frames, {matches} matches")
            self.after(5000, update)
        self.after(5000, update)

    def on_new_attendance(self, records):
        """Called from engine thread when new attendance is detected."""
        cfg = load_config()
        for r in records:
            logger.info(f"New attendance: {r['name']} ({r['staff_id']})")
            wa.notify_checkin(
                cfg,
                staff_name=r["name"],
                staff_id=r["staff_id"],
                confidence=r.get("confidence", 0.0),
                camera=r.get("camera", "unknown"),
            )
        self._refresh_dashboard()


# ─── Apply dark theme to ttk ───

def apply_dark_theme():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Treeview",
                     background=CARD_BG,
                     foreground=TEXT,
                     fieldbackground=CARD_BG,
                     bordercolor=ACCENT,
                     borderwidth=0,
                     font=("Segoe UI", 11))
    style.configure("Treeview.Heading",
                     background=NAVY,
                     foreground=GOLD,
                     borderwidth=0,
                     font=("Segoe UI", 11, "bold"))
    style.map("Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", TEXT)])
    style.configure("TScrollbar",
                     background=CARD_BG,
                     troughcolor=DARK_BG,
                     bordercolor=DARK_BG,
                     arrowcolor=TEXT_DIM)


def main():
    db.init_db()
    app = AttendanceApp()
    apply_dark_theme()
    app.mainloop()


if __name__ == "__main__":
    main()
