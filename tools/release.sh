#!/usr/bin/env bash
# 一键发布：构建 exe → 自检 → 打标签 → 推送 → 创建 GitHub Release 并上传 exe。
#
# 用法：
#   bash tools/release.sh                  # 自动把最新 vX.Y.Z 的补丁号 +1
#   bash tools/release.sh v1.2.0           # 指定标签
#   bash tools/release.sh v1.2.0 --draft   # 先发草稿
#   bash tools/release.sh --dry-run        # 只构建、自检并打印计划，不动远端
#
# 认证二选一：
#   gh auth login                 # 推荐；登录后脚本自动使用 gh
#   export GITHUB_TOKEN=ghp_xxx   # 或使用带 repo 权限的 PAT
#
# 选项：--notes-file FILE  --asset-name NAME  --no-smoke  --skip-build  --allow-dirty
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-./.venv/Scripts/python.exe}"
ASSET="dist/商人听金.exe"
ASSET_NAME="商人听金.exe"
TAG=""
DRAFT=0
PRERELEASE=0
NOTES_FILE=""
SMOKE=1
BUILD=1
DRY=0
ALLOW_DIRTY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --draft) DRAFT=1 ;;
    --prerelease) PRERELEASE=1 ;;
    --notes-file) NOTES_FILE="${2:?--notes-file 需要文件路径}"; shift ;;
    --asset-name) ASSET_NAME="${2:?--asset-name 需要名称}"; shift ;;
    --no-smoke) SMOKE=0 ;;
    --skip-build) BUILD=0 ;;
    --dry-run) DRY=1 ;;
    --allow-dirty) ALLOW_DIRTY=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    -*) echo "未知选项：$1" >&2; exit 2 ;;
    *) TAG="$1" ;;
  esac
  shift
done

command -v git >/dev/null || { echo "缺少 git" >&2; exit 1; }

if [ "$ALLOW_DIRTY" -eq 0 ] && [ -n "$(git status --porcelain)" ]; then
  echo "工作区有未提交的改动：" >&2
  git status --short >&2
  echo "先提交，或加 --allow-dirty" >&2
  exit 1
fi

REMOTE="$(git remote get-url origin 2>/dev/null || true)"
case "$REMOTE" in
  git@github.com:*) SLUG="${REMOTE#git@github.com:}" ;;
  https://github.com/*) SLUG="${REMOTE#https://github.com/}" ;;
  *) echo "origin 不是 GitHub 仓库：${REMOTE:-<无>}" >&2; exit 1 ;;
esac
SLUG="${SLUG%.git}"
[ -n "$SLUG" ] || { echo "无法解析仓库名" >&2; exit 1; }

if [ -z "$TAG" ]; then
  LAST="$(git tag --list 'v*.*.*' --sort=-v:refname | head -n1 || true)"
  if [ -z "$LAST" ]; then
    TAG="v1.0.0"
  else
    IFS=. read -r MAJ MIN PATCH <<< "${LAST#v}"
    TAG="v${MAJ}.${MIN}.$((PATCH + 1))"
  fi
fi

echo "== 1/5 构建 =="
if [ "$BUILD" -eq 1 ]; then
  bash tools/build_exe.sh
else
  echo "   跳过"
fi
[ -f "$ASSET" ] || { echo "找不到产物：$ASSET" >&2; exit 1; }
SIZE="$(wc -c < "$ASSET" | tr -d ' ')"
echo "   $ASSET  $((SIZE / 1048576)) MB"
if [ "$SIZE" -lt 30000000 ]; then
  echo "产物小于 30 MB，构建可能不完整" >&2
  exit 1
fi

echo "== 2/5 自检 =="
if [ "$SMOKE" -eq 1 ]; then
  "$PYTHON" tools/smoke_test.py "$ASSET" --timeout 12
else
  echo "   跳过"
fi

echo "== 3/5 发布说明 =="
if [ -n "$NOTES_FILE" ]; then
  BODY="$(cat "$NOTES_FILE")"
else
  PREV="$(git describe --tags --abbrev=0 2>/dev/null || true)"
  if [ -n "$PREV" ]; then
    BODY="$(git log --pretty=format:'- %s' "${PREV}..HEAD")"
  else
    BODY="$(git log --pretty=format:'- %s' | head -n 20 || true)"
  fi
fi
if [ -z "$BODY" ]; then
  BODY="构建产物：${ASSET_NAME}"
fi
printf '%s\n' "$BODY" | sed 's/^/   /'

if [ "$DRY" -eq 1 ]; then
  echo "== 4/5 演练（未打标签、未推送、未创建 Release）=="
  echo "   仓库：$SLUG"
  echo "   标签：$TAG"
  echo "   资产：$ASSET -> $ASSET_NAME"
  exit 0
fi

echo "== 4/5 打标签并推送 =="
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "标签 $TAG 已存在，换一个版本号" >&2
  exit 1
fi
git tag -a "$TAG" -m "$TAG"
git push origin HEAD
git push origin "$TAG"
echo "   已推送 $TAG"

echo "== 5/5 创建 Release 并上传 =="
DRAFT_FLAG=false
if [ "$DRAFT" -eq 1 ]; then DRAFT_FLAG=true; fi
PRE_FLAG=false
if [ "$PRERELEASE" -eq 1 ]; then PRE_FLAG=true; fi

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  GH_ARGS=(release create "$TAG" "$ASSET#$ASSET_NAME" --title "$TAG" --notes "$BODY")
  if [ "$DRAFT" -eq 1 ]; then GH_ARGS+=(--draft); fi
  if [ "$PRERELEASE" -eq 1 ]; then GH_ARGS+=(--prerelease); fi
  gh "${GH_ARGS[@]}"
  echo "完成：https://github.com/$SLUG/releases/tag/$TAG"
  exit 0
fi

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  echo "没有可用的认证：先 gh auth login，或 export GITHUB_TOKEN=<带 repo 权限的 PAT>" >&2
  echo "（标签已推送，补建 Release 可直接在网页上操作）" >&2
  exit 1
fi

PAYLOAD="$("$PYTHON" - "$TAG" "$BODY" "$DRAFT_FLAG" "$PRE_FLAG" <<'PY'
import json
import sys

tag, body, draft, prerelease = sys.argv[1:5]
print(json.dumps({
    'tag_name': tag,
    'name': tag,
    'body': body,
    'draft': draft == 'true',
    'prerelease': prerelease == 'true',
}, ensure_ascii=False))
PY
)"

RESP="$(curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/$SLUG/releases" \
  -d "$PAYLOAD")"

RELEASE_ID="$(printf '%s' "$RESP" | "$PYTHON" -c 'import json, sys; print(json.load(sys.stdin).get("id", ""))' 2>/dev/null || true)"
if [ -z "$RELEASE_ID" ]; then
  echo "创建 Release 失败：" >&2
  printf '%s\n' "$RESP" >&2
  exit 1
fi

ENCODED="$("$PYTHON" -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$ASSET_NAME")"
curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@$ASSET" \
  "https://uploads.github.com/repos/$SLUG/releases/$RELEASE_ID/assets?name=$ENCODED" > /dev/null

echo "完成：https://github.com/$SLUG/releases/tag/$TAG"
