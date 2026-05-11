"""
Build script to create a standalone .exe for Windows.

Usage (on Windows):
    pip install pyinstaller
    python build_exe.py

This creates: dist/LawMinisterAttendance.exe
"""

import subprocess
import sys


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "LawMinisterAttendance",
        "--add-data", "frontend;frontend",
        "--add-data", "backend;backend",
        "--hidden-import", "customtkinter",
        "--hidden-import", "insightface",
        "--hidden-import", "onnxruntime",
        "--hidden-import", "cv2",
        "--hidden-import", "httpx",
        "--hidden-import", "PIL",
        "--hidden-import", "numpy",
        "--collect-all", "customtkinter",
        "--collect-all", "insightface",
        "desktop_app.py",
    ]

    print("Building standalone executable...")
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\nBuild successful!")
        print("Executable: dist/LawMinisterAttendance/LawMinisterAttendance.exe")
        print("\nTo distribute:")
        print("  1. Copy the entire dist/LawMinisterAttendance/ folder")
        print("  2. Run LawMinisterAttendance.exe on the target PC")
    else:
        print("\nBuild failed! Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    build()
