"""
Build script to create a standalone .exe for the Office Attendance Engine.

Usage (on Windows):
    pip install pyinstaller
    pip install -r office_engine/requirements.txt
    pip install customtkinter
    python build_office_exe.py

This creates: dist/LawMinisterOfficeEngine/LawMinisterOfficeEngine.exe

To install on the office PC:
    1. Copy the entire dist/LawMinisterOfficeEngine/ folder to a USB drive
    2. Copy folder to the office PC (e.g., C:\\LawMinisterAttendance\\)
    3. Double-click LawMinisterOfficeEngine.exe
    4. Configure cameras in the GUI
    5. Click "Start Engine"
    6. (Optional) Run install_service.bat as Administrator for auto-start
"""

import subprocess
import sys
from pathlib import Path


def build():
    # Determine platform-specific separator
    sep = ";" if sys.platform == "win32" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "LawMinisterOfficeEngine",
        # Include office engine package
        "--add-data", f"office_engine{sep}office_engine",
        # Include default config
        "--add-data", f"office_config.json{sep}.",
        # Include service installer
        "--add-data", f"office_engine/install_service.bat{sep}.",
        # Hidden imports
        "--hidden-import", "customtkinter",
        "--hidden-import", "insightface",
        "--hidden-import", "insightface.app",
        "--hidden-import", "insightface.app.face_analysis",
        "--hidden-import", "insightface.model_zoo",
        "--hidden-import", "onnxruntime",
        "--hidden-import", "cv2",
        "--hidden-import", "httpx",
        "--hidden-import", "httpx._transports",
        "--hidden-import", "httpx._transports.default",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageEnhance",
        "--hidden-import", "numpy",
        "--hidden-import", "office_engine",
        "--hidden-import", "office_engine.config",
        "--hidden-import", "office_engine.cloud_sync",
        "--hidden-import", "office_engine.camera_reader",
        "--hidden-import", "office_engine.face_processor",
        "--hidden-import", "office_engine.engine",
        # Collect all customtkinter assets
        "--collect-all", "customtkinter",
        "--collect-all", "insightface",
        # Entry point
        "office_engine/gui_app.py",
    ]

    print("=" * 60)
    print("LAW MINISTER OFFICE ENGINE — BUILD")
    print("=" * 60)
    print()
    print("Building standalone executable...")
    print()

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print()
        print("=" * 60)
        print("BUILD SUCCESSFUL!")
        print("=" * 60)
        print()
        print("Output: dist/LawMinisterOfficeEngine/")
        print("Executable: dist/LawMinisterOfficeEngine/LawMinisterOfficeEngine.exe")
        print()
        print("To install on the office PC:")
        print("  1. Copy the dist/LawMinisterOfficeEngine/ folder to a USB drive")
        print("  2. Copy to the office PC (e.g., C:\\LawMinisterAttendance\\)")
        print("  3. Double-click LawMinisterOfficeEngine.exe")
        print("  4. Configure cameras in the Cameras tab")
        print("  5. Click 'Start Engine'")
        print()
        print("For auto-start on boot:")
        print("  Run install_service.bat as Administrator")
    else:
        print()
        print("BUILD FAILED! Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    build()
