#!/usr/bin/env bash
# 重新打包发布版 exe。运行：bash tools/build_exe.sh   产物：dist/商人听金.exe
set -e
cd "$(dirname "$0")/.."
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

# scipy 的 _distn_infrastructure.py 在冻结环境下会崩溃，先打补丁（幂等）
./.venv/Scripts/python.exe tools/patch_scipy_for_pyinstaller.py

./.venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name 商人听金 \
  --add-data "catalog.json;." \
  --add-data "reference;reference" \
  --hidden-import soundcard \
  --hidden-import soundfile \
  merchant_listener.py

# 中间产物不留痕
rm -rf build 商人听金.spec
echo "OK -> dist/商人听金.exe"
