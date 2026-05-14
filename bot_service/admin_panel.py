"""
Law Minister Bot — Desktop Admin Panel

A standalone desktop application for administrators to:
- View real-time message logs
- Monitor bot status
- Manage staff
- Generate and download reports
- View attendance records

Run: python -m bot_service.admin_panel
"""

import logging
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    CTK = True
except ImportError:
    ctk = None
    CTK = False

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lm_bot.admin_panel")

# Colors
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

# Server URL (local bot service or remote)
DEFAULT_SERVER = os.getenv("LM_BOT_SERVER", "http://localhost:8000")


class AdminPanel:
    """Desktop Admin Panel for Law Minister Bot."""

    def __init__(self):
        self.server_url = DEFAULT_SERVER

        if CTK:
            self.root = ctk.CTk()
            self.root.title("Law Minister Bot — Admin Panel")
            self.root.geometry("1200x800")
        else:
            self.root = tk.Tk()
            self.root.title("Law Minister Bot — Admin Panel")
            self.root.geometry("1200x800")
            self.root.configure(bg=DARK_BG)

        self._build_ui()
        self._auto_refresh()

    def _build_ui(self):
        """Build the main UI layout."""
        # Top bar
        if CTK:
            top_frame = ctk.CTkFrame(self.root, height=60, fg_color=NAVY)
            top_frame.pack(fill="x", padx=0, pady=0)
            top_frame.pack_propagate(False)

            ctk.CTkLabel(
                top_frame,
                text="⚖️  Law Minister Bot — Admin Panel",
                font=ctk.CTkFont(size=20, weight="bold"),
                text_color=GOLD,
            ).pack(side="left", padx=20, pady=15)

            # Server URL entry
            self.server_entry = ctk.CTkEntry(top_frame, width=300, placeholder_text="Server URL")
            self.server_entry.pack(side="right", padx=10, pady=15)
            self.server_entry.insert(0, self.server_url)

            ctk.CTkButton(
                top_frame, text="Connect", width=80,
                command=self._connect_server,
            ).pack(side="right", padx=5, pady=15)

            # Status label
            self.status_label = ctk.CTkLabel(
                top_frame, text="● Disconnected", text_color=DANGER,
                font=ctk.CTkFont(size=12),
            )
            self.status_label.pack(side="right", padx=10, pady=15)
        else:
            top_frame = tk.Frame(self.root, height=60, bg=NAVY)
            top_frame.pack(fill="x")
            top_frame.pack_propagate(False)

            tk.Label(
                top_frame, text="⚖️  Law Minister Bot — Admin Panel",
                font=("Arial", 16, "bold"), fg=GOLD, bg=NAVY,
            ).pack(side="left", padx=20, pady=15)

            self.status_label = tk.Label(
                top_frame, text="● Disconnected", fg=DANGER, bg=NAVY,
                font=("Arial", 10),
            )
            self.status_label.pack(side="right", padx=10, pady=15)

        # Tabs
        if CTK:
            self.tabview = ctk.CTkTabview(self.root)
            self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

            self.tab_messages = self.tabview.add("Messages")
            self.tab_staff = self.tabview.add("Staff")
            self.tab_attendance = self.tabview.add("Attendance")
            self.tab_reports = self.tabview.add("Reports")
            self.tab_settings = self.tabview.add("Settings")
        else:
            notebook = ttk.Notebook(self.root)
            notebook.pack(fill="both", expand=True, padx=10, pady=10)

            self.tab_messages = ttk.Frame(notebook)
            self.tab_staff = ttk.Frame(notebook)
            self.tab_attendance = ttk.Frame(notebook)
            self.tab_reports = ttk.Frame(notebook)
            self.tab_settings = ttk.Frame(notebook)

            notebook.add(self.tab_messages, text="Messages")
            notebook.add(self.tab_staff, text="Staff")
            notebook.add(self.tab_attendance, text="Attendance")
            notebook.add(self.tab_reports, text="Reports")
            notebook.add(self.tab_settings, text="Settings")

        self._build_messages_tab()
        self._build_staff_tab()
        self._build_attendance_tab()
        self._build_reports_tab()
        self._build_settings_tab()

    def _build_messages_tab(self):
        """Build the messages tab with log viewer."""
        parent = self.tab_messages

        if CTK:
            # Toolbar
            toolbar = ctk.CTkFrame(parent, fg_color="transparent")
            toolbar.pack(fill="x", padx=10, pady=5)

            ctk.CTkButton(toolbar, text="🔄 Refresh", width=100,
                          command=self._load_messages).pack(side="left", padx=5)
            ctk.CTkLabel(toolbar, text="Days:").pack(side="left", padx=(20, 5))
            self.days_var = ctk.StringVar(value="7")
            ctk.CTkEntry(toolbar, width=50, textvariable=self.days_var).pack(side="left")

            # Message table
            self.msg_tree = ttk.Treeview(
                parent,
                columns=("dir", "from", "to", "content", "category", "time"),
                show="headings",
                height=20,
            )
            self.msg_tree.heading("dir", text="Direction")
            self.msg_tree.heading("from", text="From")
            self.msg_tree.heading("to", text="To")
            self.msg_tree.heading("content", text="Content")
            self.msg_tree.heading("category", text="Category")
            self.msg_tree.heading("time", text="Timestamp")

            self.msg_tree.column("dir", width=80)
            self.msg_tree.column("from", width=120)
            self.msg_tree.column("to", width=120)
            self.msg_tree.column("content", width=400)
            self.msg_tree.column("category", width=100)
            self.msg_tree.column("time", width=150)

            self.msg_tree.pack(fill="both", expand=True, padx=10, pady=5)

            scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.msg_tree.yview)
            self.msg_tree.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
        else:
            toolbar = tk.Frame(parent, bg=DARK_BG)
            toolbar.pack(fill="x", padx=10, pady=5)

            tk.Button(toolbar, text="Refresh", command=self._load_messages).pack(side="left", padx=5)

            self.msg_tree = ttk.Treeview(
                parent,
                columns=("dir", "from", "to", "content", "category", "time"),
                show="headings",
                height=20,
            )
            for col, text, width in [
                ("dir", "Direction", 80), ("from", "From", 120), ("to", "To", 120),
                ("content", "Content", 400), ("category", "Category", 100), ("time", "Timestamp", 150)
            ]:
                self.msg_tree.heading(col, text=text)
                self.msg_tree.column(col, width=width)
            self.msg_tree.pack(fill="both", expand=True, padx=10, pady=5)

    def _build_staff_tab(self):
        """Build the staff management tab."""
        parent = self.tab_staff

        if CTK:
            toolbar = ctk.CTkFrame(parent, fg_color="transparent")
            toolbar.pack(fill="x", padx=10, pady=5)

            ctk.CTkButton(toolbar, text="🔄 Refresh", width=100,
                          command=self._load_staff).pack(side="left", padx=5)
            ctk.CTkButton(toolbar, text="➕ Add Staff", width=100,
                          command=self._add_staff_dialog).pack(side="left", padx=5)

            self.staff_tree = ttk.Treeview(
                parent,
                columns=("name", "phone", "designation"),
                show="headings",
                height=15,
            )
            self.staff_tree.heading("name", text="Name")
            self.staff_tree.heading("phone", text="Phone")
            self.staff_tree.heading("designation", text="Designation")
            self.staff_tree.column("name", width=200)
            self.staff_tree.column("phone", width=150)
            self.staff_tree.column("designation", width=200)
            self.staff_tree.pack(fill="both", expand=True, padx=10, pady=5)
        else:
            toolbar = tk.Frame(parent, bg=DARK_BG)
            toolbar.pack(fill="x", padx=10, pady=5)
            tk.Button(toolbar, text="Refresh", command=self._load_staff).pack(side="left", padx=5)
            tk.Button(toolbar, text="Add Staff", command=self._add_staff_dialog).pack(side="left", padx=5)

            self.staff_tree = ttk.Treeview(
                parent, columns=("name", "phone", "designation"), show="headings", height=15,
            )
            for col, text, w in [("name", "Name", 200), ("phone", "Phone", 150), ("designation", "Designation", 200)]:
                self.staff_tree.heading(col, text=text)
                self.staff_tree.column(col, width=w)
            self.staff_tree.pack(fill="both", expand=True, padx=10, pady=5)

    def _build_attendance_tab(self):
        """Build the attendance viewer tab."""
        parent = self.tab_attendance

        if CTK:
            toolbar = ctk.CTkFrame(parent, fg_color="transparent")
            toolbar.pack(fill="x", padx=10, pady=5)

            ctk.CTkButton(toolbar, text="🔄 Refresh", width=100,
                          command=self._load_attendance).pack(side="left", padx=5)
            ctk.CTkLabel(toolbar, text="Date (YYYY-MM-DD):").pack(side="left", padx=(20, 5))
            self.att_date_var = ctk.StringVar(value=str(date.today()))
            ctk.CTkEntry(toolbar, width=120, textvariable=self.att_date_var).pack(side="left")

            self.att_tree = ttk.Treeview(
                parent,
                columns=("name", "date", "time", "status"),
                show="headings",
                height=15,
            )
            self.att_tree.heading("name", text="Staff Name")
            self.att_tree.heading("date", text="Date")
            self.att_tree.heading("time", text="Time")
            self.att_tree.heading("status", text="Status")
            self.att_tree.column("name", width=200)
            self.att_tree.column("date", width=120)
            self.att_tree.column("time", width=120)
            self.att_tree.column("status", width=100)
            self.att_tree.pack(fill="both", expand=True, padx=10, pady=5)
        else:
            toolbar = tk.Frame(parent, bg=DARK_BG)
            toolbar.pack(fill="x", padx=10, pady=5)
            tk.Button(toolbar, text="Refresh", command=self._load_attendance).pack(side="left", padx=5)

            self.att_tree = ttk.Treeview(
                parent, columns=("name", "date", "time", "status"), show="headings", height=15,
            )
            for col, text, w in [("name", "Name", 200), ("date", "Date", 120), ("time", "Time", 120), ("status", "Status", 100)]:
                self.att_tree.heading(col, text=text)
                self.att_tree.column(col, width=w)
            self.att_tree.pack(fill="both", expand=True, padx=10, pady=5)

    def _build_reports_tab(self):
        """Build the reports download tab."""
        parent = self.tab_reports

        if CTK:
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(fill="both", expand=True, padx=20, pady=20)

            ctk.CTkLabel(
                frame, text="Report Generation",
                font=ctk.CTkFont(size=18, weight="bold"),
            ).pack(pady=10)

            ctk.CTkButton(
                frame, text="📊 Download Message Summary (Excel)",
                width=300, height=40,
                command=self._download_message_report,
            ).pack(pady=10)

            ctk.CTkButton(
                frame, text="📋 Download Attendance Report (Excel)",
                width=300, height=40,
                command=self._download_attendance_report,
            ).pack(pady=10)

            ctk.CTkButton(
                frame, text="🌐 Open Bot Dashboard in Browser",
                width=300, height=40,
                command=lambda: webbrowser.open(self.server_url),
            ).pack(pady=10)
        else:
            frame = tk.Frame(parent, bg=DARK_BG)
            frame.pack(fill="both", expand=True, padx=20, pady=20)

            tk.Label(frame, text="Report Generation", font=("Arial", 14, "bold"),
                     fg=TEXT, bg=DARK_BG).pack(pady=10)
            tk.Button(frame, text="Download Message Summary", command=self._download_message_report).pack(pady=10)
            tk.Button(frame, text="Download Attendance Report", command=self._download_attendance_report).pack(pady=10)

    def _build_settings_tab(self):
        """Build the settings tab."""
        parent = self.tab_settings

        if CTK:
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(fill="both", expand=True, padx=20, pady=20)

            ctk.CTkLabel(
                frame, text="Bot Settings",
                font=ctk.CTkFont(size=18, weight="bold"),
            ).pack(pady=10)

            # Server URL
            ctk.CTkLabel(frame, text="Backend Server URL:").pack(anchor="w", padx=10, pady=(10, 0))
            self.settings_server = ctk.CTkEntry(frame, width=400)
            self.settings_server.pack(anchor="w", padx=10, pady=5)
            self.settings_server.insert(0, self.server_url)

            ctk.CTkButton(
                frame, text="Save Settings", width=150,
                command=self._save_settings,
            ).pack(pady=20)

            # Info
            info = (
                "Admin Phone: 918796105084 (Ali)\n"
                "Law Minister Phone ID: 1168433719678061\n"
                "Bot Number: +91 84489 43232\n\n"
                "Commands via WhatsApp:\n"
                "• summary — Get Excel message report\n"
                "• staff — List all staff\n"
                "• today — Today's attendance\n"
                "• admin help — Show all commands"
            )
            ctk.CTkLabel(
                frame, text=info, justify="left",
                font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
            ).pack(anchor="w", padx=10, pady=20)
        else:
            frame = tk.Frame(parent, bg=DARK_BG)
            frame.pack(fill="both", expand=True, padx=20, pady=20)
            tk.Label(frame, text="Bot Settings", font=("Arial", 14, "bold"),
                     fg=TEXT, bg=DARK_BG).pack(pady=10)

    # ---------- Actions ----------

    def _connect_server(self):
        """Update server URL and check connection."""
        if CTK:
            self.server_url = self.server_entry.get().strip().rstrip("/")
        self._check_connection()

    def _check_connection(self):
        """Check if the bot server is reachable."""
        import urllib.request
        try:
            resp = urllib.request.urlopen(f"{self.server_url}/health", timeout=5)
            if resp.status == 200:
                if CTK:
                    self.status_label.configure(text="● Connected", text_color=SUCCESS)
                else:
                    self.status_label.config(text="● Connected", fg=SUCCESS)
                return True
        except Exception:
            pass

        if CTK:
            self.status_label.configure(text="● Disconnected", text_color=DANGER)
        else:
            self.status_label.config(text="● Disconnected", fg=DANGER)
        return False

    def _load_messages(self):
        """Load messages from server."""
        import urllib.request
        import json

        days = 7
        if CTK:
            try:
                days = int(self.days_var.get())
            except ValueError:
                pass

        try:
            url = f"{self.server_url}/api/messages?days={days}"
            resp = urllib.request.urlopen(url, timeout=10)
            data = json.loads(resp.read().decode())
            messages = data.get("messages", [])

            # Clear tree
            for item in self.msg_tree.get_children():
                self.msg_tree.delete(item)

            for msg in messages:
                self.msg_tree.insert("", "end", values=(
                    msg.get("direction", ""),
                    msg.get("sender", ""),
                    msg.get("recipient", ""),
                    (msg.get("content", "") or "")[:100],
                    msg.get("category", ""),
                    msg.get("timestamp", ""),
                ))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load messages: {e}")

    def _load_staff(self):
        """Load staff list from server."""
        import urllib.request
        import json

        try:
            resp = urllib.request.urlopen(f"{self.server_url}/api/staff", timeout=10)
            data = json.loads(resp.read().decode())
            staff = data.get("staff", [])

            for item in self.staff_tree.get_children():
                self.staff_tree.delete(item)

            for s in staff:
                self.staff_tree.insert("", "end", values=(
                    s.get("name", ""),
                    s.get("phone", ""),
                    s.get("designation", ""),
                ))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load staff: {e}")

    def _load_attendance(self):
        """Load attendance records from server."""
        import urllib.request
        import json

        date_str = ""
        if CTK:
            date_str = self.att_date_var.get().strip()

        try:
            url = f"{self.server_url}/api/attendance?date={date_str}"
            resp = urllib.request.urlopen(url, timeout=10)
            data = json.loads(resp.read().decode())
            records = data.get("records", [])

            for item in self.att_tree.get_children():
                self.att_tree.delete(item)

            for r in records:
                self.att_tree.insert("", "end", values=(
                    r.get("staff_name", ""),
                    r.get("date", ""),
                    r.get("time", ""),
                    r.get("status", ""),
                ))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load attendance: {e}")

    def _add_staff_dialog(self):
        """Show dialog to add a new staff member."""
        if CTK:
            dialog = ctk.CTkInputDialog(text="Enter: Name, Phone, Designation (comma separated)", title="Add Staff")
            result = dialog.get_input()
        else:
            result = tk.simpledialog.askstring("Add Staff", "Enter: Name, Phone, Designation (comma separated)")

        if result:
            parts = [p.strip() for p in result.split(",")]
            if len(parts) >= 2:
                import urllib.request
                import json
                name, phone = parts[0], parts[1]
                designation = parts[2] if len(parts) > 2 else ""
                try:
                    data = json.dumps({"name": name, "phone": phone, "designation": designation}).encode()
                    req = urllib.request.Request(
                        f"{self.server_url}/api/staff",
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=10)
                    messagebox.showinfo("Success", f"Added {name}")
                    self._load_staff()
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to add staff: {e}")
            else:
                messagebox.showwarning("Invalid", "Please enter at least Name and Phone separated by comma")

    def _download_message_report(self):
        """Download message report Excel."""
        import urllib.request
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile="message_summary.xlsx",
        )
        if filepath:
            try:
                url = f"{self.server_url}/api/report/messages?days=7"
                urllib.request.urlretrieve(url, filepath)
                messagebox.showinfo("Success", f"Report saved to:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Error", f"Download failed: {e}")

    def _download_attendance_report(self):
        """Download attendance report Excel."""
        import urllib.request
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile="attendance_report.xlsx",
        )
        if filepath:
            try:
                date_str = ""
                if CTK:
                    date_str = self.att_date_var.get().strip()
                url = f"{self.server_url}/api/report/attendance?date={date_str}"
                urllib.request.urlretrieve(url, filepath)
                messagebox.showinfo("Success", f"Report saved to:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Error", f"Download failed: {e}")

    def _save_settings(self):
        """Save settings."""
        if CTK:
            self.server_url = self.settings_server.get().strip().rstrip("/")
            if hasattr(self, "server_entry"):
                self.server_entry.delete(0, "end")
                self.server_entry.insert(0, self.server_url)
        messagebox.showinfo("Saved", "Settings saved successfully")

    def _auto_refresh(self):
        """Auto-refresh connection status every 30 seconds."""
        self._check_connection()
        self.root.after(30000, self._auto_refresh)

    def run(self):
        """Start the admin panel."""
        self.root.mainloop()


if __name__ == "__main__":
    panel = AdminPanel()
    panel.run()
