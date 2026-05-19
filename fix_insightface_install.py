"""Fix insightface installation by removing C++ extension requirement."""
import os
import glob
import subprocess
import sys


def fix_and_install():
    home = os.path.expanduser("~")
    iftemp = os.path.join(home, "Desktop", "iftemp")

    # Find extracted insightface directory
    dirs = glob.glob(os.path.join(iftemp, "insightface-*/"))
    if not dirs:
        print("ERROR: insightface source not found in ~/Desktop/iftemp/")
        print("Run first: py -3.12 -m pip download insightface --no-binary insightface -d %USERPROFILE%\\Desktop\\iftemp")
        return

    src_dir = dirs[0]
    setup_py = os.path.join(src_dir, "setup.py")

    if not os.path.exists(setup_py):
        print(f"ERROR: setup.py not found at {setup_py}")
        return

    # Read setup.py and remove ext_modules
    lines = open(setup_py).readlines()
    new_lines = []
    skip = False
    bracket_depth = 0

    for line in lines:
        if "ext_modules" in line and not skip:
            new_lines.append("    ext_modules=[],\n")
            bracket_depth = line.count("[") - line.count("]")
            if bracket_depth > 0:
                skip = True
            continue
        if skip:
            bracket_depth += line.count("[") - line.count("]")
            if bracket_depth <= 0:
                skip = False
            continue
        new_lines.append(line)

    open(setup_py, "w").writelines(new_lines)
    print("Patched setup.py — removed C++ extension requirement")

    # Install from patched source
    print(f"Installing from {src_dir}...")
    subprocess.run([sys.executable, "-m", "pip", "install", src_dir])


if __name__ == "__main__":
    fix_and_install()
