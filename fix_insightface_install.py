"""Install insightface by copying files directly — bypasses C++ build requirement."""
import os
import glob
import shutil
import subprocess
import sys


def fix_and_install():
    home = os.path.expanduser("~")
    iftemp = os.path.join(home, "Desktop", "iftemp")

    # Find extracted insightface directory
    dirs = glob.glob(os.path.join(iftemp, "insightface-*/"))
    if not dirs:
        print("ERROR: insightface source not found in ~/Desktop/iftemp/")
        return

    src_dir = dirs[0]
    src_pkg = os.path.join(src_dir, "insightface")

    if not os.path.isdir(src_pkg):
        print(f"ERROR: insightface package not found at {src_pkg}")
        return

    # Find site-packages directory
    site_packages = None
    for p in sys.path:
        if "site-packages" in p and os.path.isdir(p):
            site_packages = p
            break

    if not site_packages:
        print("ERROR: Could not find site-packages directory")
        return

    # Copy insightface package directly into site-packages
    dst_pkg = os.path.join(site_packages, "insightface")
    if os.path.exists(dst_pkg):
        shutil.rmtree(dst_pkg)
    shutil.copytree(src_pkg, dst_pkg)
    print(f"Copied insightface to {dst_pkg}")

    # Install dependencies
    print("Installing dependencies...")
    deps = [
        "numpy", "onnx", "onnxruntime", "Pillow", "scipy",
        "scikit-learn", "albumentations", "easydict", "prettytable",
        "tqdm", "pyyaml", "cython",
    ]
    subprocess.run([sys.executable, "-m", "pip", "install"] + deps)

    # Verify import works
    print("\nVerifying insightface import...")
    result = subprocess.run(
        [sys.executable, "-c", "from insightface.app import FaceAnalysis; print('SUCCESS — insightface imported!')"],
        capture_output=True, text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(f"Warning: {result.stderr.strip()}")
    else:
        print("InsightFace installed successfully!")


if __name__ == "__main__":
    fix_and_install()
