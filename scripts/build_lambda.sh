#!/usr/bin/env bash
# =============================================================================
# Lambda デプロイパッケージを作る（Docker 不要）
# =============================================================================
# Claude のメモリ通り、Windows からでも --platform で Linux wheel を取得できる:
#   pip install --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all:
# これで cryptography / pydantic-core などの C/Rust 拡張も Lambda(Amazon Linux x86_64)用に揃う。
#
# 使い方:  bash scripts/build_lambda.sh
# 生成物:  backend/build/  （CDK が lambda.Code.fromAsset で取り込む）
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
BUILD="$BACKEND/build"

# pip 本体は手元の python のものを使う（3.10でも --python-version 3.12 指定でOK）
PY="${PYTHON:-python}"

echo "[1/4] clean $BUILD"
rm -rf "$BUILD"
mkdir -p "$BUILD"

echo "[2/4] pip install (linux x86_64 / py3.12 wheels) -> build/"
"$PY" -m pip install \
  --platform manylinux2014_x86_64 \
  --python-version 3.12 \
  --implementation cp \
  --only-binary=:all: \
  --target "$BUILD" \
  -r "$BACKEND/requirements-lambda.txt"

echo "[3/4] copy app code"
cp -r "$BACKEND/app" "$BUILD/app"
cp "$BACKEND/handler.py" "$BUILD/handler.py"

echo "[4/4] strip __pycache__ (dist-info は残す: importlib.metadata 用)"
find "$BUILD" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true

echo "OK -> $BUILD"
