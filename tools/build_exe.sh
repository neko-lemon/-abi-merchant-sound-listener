#!/usr/bin/env bash
# 重新打包发布版 exe。运行：bash tools/build_exe.sh   产物：dist/商人听金.exe
# 可用 PYTHON=/path/to/python 覆盖解释器（CI 里用系统 python）。
set -e
cd "$(dirname "$0")/.."
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
PYTHON="${PYTHON:-./.venv/Scripts/python.exe}"

# scipy 的 _distn_infrastructure.py 在冻结环境下会崩溃，先打补丁（幂等）
"$PYTHON" tools/patch_scipy_for_pyinstaller.py

# 正在运行的 exe 会锁住 dist 里的文件；先删旧产物，删不掉说明程序还开着。
if ! rm -f "dist/商人听金.exe" 2>/dev/null; then
  echo "dist/商人听金.exe 正被占用（程序还在运行？）先关掉它再打包" >&2
  exit 1
fi

"$PYTHON" -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name 商人听金 \
  --add-data "catalog.json;." \
  --add-data "reference;reference" \
  --hidden-import soundcard \
  --hidden-import soundfile \
  merchant_listener.py

# 中间产物不留痕
rm -rf build 商人听金.spec
echo "OK -> dist/商人听金.exe"
