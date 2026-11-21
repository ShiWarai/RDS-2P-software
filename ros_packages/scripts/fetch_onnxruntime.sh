#!/bin/bash
# Скачивает и распаковывает onnxruntime SDK 1.19.2 в src/rds_2p_inference/external_lib.
# Единственный источник этой логики: её вызывают build_for_robot.sh,
# build_for_desktop.sh, docker/build_robot.sh и docker/build_desktop.sh (prepare).
# Архитектура берётся от машины-хоста (uname -m) — в CI это нативные runner'ы по arch.
# Идемпотентен: если SDK уже на месте — ничего не делает.
#
# ВАЖНО: github.com/microsoft/onnxruntime удалён (404 с 2026-11-17), релизных
# архивов там больше нет. Официальный NuGet-пакет Microsoft.ML.OnnxRuntime 1.19.2
# содержит и C++ headers (build/native/include), и Linux-библиотеки
# (runtimes/linux-{x64,arm64}/native), поэтому берём его.
set -eu
WS="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EL="$WS/src/rds_2p_inference/external_lib"
NUPKG_URL="https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime/1.19.2/microsoft.ml.onnxruntime.1.19.2.nupkg"
NUPKG_NAME="microsoft.ml.onnxruntime.1.19.2.nupkg"
NUPKG_SHA512="aDzUYFe+9m2OyjLXEyQfLw3kMGB0CUWSuTSIaNGOuymyG5u12UZqnSdCK1IWP4ygLz6x9PFtIXQPcE0sgFj25A=="
A="$(uname -m)"
case "$A" in
  x86_64)
    ORT=onnxruntime-linux-x64-1.19.2
    RID=linux-x64
    ORT_SHA256=9c8139e1856568f068f1cad78fc9798084941db50be7c201a1dbdcfd18105433
    ;;
  aarch64|arm64)
    ORT=onnxruntime-linux-aarch64-1.19.2
    RID=linux-arm64
    ORT_SHA256=d9abfb42ddd120855f93ccb3c97a0918ac5bef209485db0dc3a36a3d188671ab
    ;;
  *)
    echo "❌ unsupported arch: $A" >&2
    exit 1
    ;;
esac

verify_nupkg() {
  local f="$1" actual
  if command -v openssl >/dev/null 2>&1; then
    actual=$(openssl dgst -sha512 -binary "$f" | openssl base64 -A)
  else
    actual=$(python3 -c 'import base64,hashlib,sys; print(base64.b64encode(hashlib.sha512(open(sys.argv[1],"rb").read()).digest()).decode())' "$f")
  fi
  [ "$actual" = "$NUPKG_SHA512" ]
}

if [ -d "$EL/$ORT" ] \
   && [ -f "$EL/$ORT/lib/libonnxruntime.so" ] \
   && [ -f "$EL/$ORT/include/onnxruntime_cxx_api.h" ]; then
  echo "ℹ️ OnnxRuntime уже установлен: $ORT"
  exit 0
fi
if [ -d "$EL/$ORT" ]; then
  echo "⚠️ OnnxRuntime $ORT распакован неполностью — удаляем и скачиваем заново"
  rm -rf "$EL/$ORT"
fi
echo "📥 Скачиваем OnnxRuntime 1.19.2 ($A) из официального NuGet..."
mkdir -p "$EL"
cd "$EL"
# Убираем артефакты старой загрузки с github.com/microsoft/onnxruntime (404 → 9 байт)
rm -f "$EL/$ORT.tgz" "$EL/$ORT.tgz.part"
NUPKG="$EL/$NUPKG_NAME"
rm -f "$NUPKG.part"
if [ -f "$NUPKG" ] && ! verify_nupkg "$NUPKG"; then
  echo "⚠️ Кэш $NUPKG_NAME повреждён — перекачиваем"
  rm -f "$NUPKG"
fi
if [ ! -f "$NUPKG" ]; then
  if ! curl -fL --retry 3 --retry-delay 2 -o "$NUPKG.part" "$NUPKG_URL"; then
    echo "❌ Не удалось скачать $NUPKG_URL" >&2
    rm -f "$NUPKG.part"
    exit 1
  fi
  if ! verify_nupkg "$NUPKG.part"; then
    echo "❌ SHA512 не совпал для $NUPKG_NAME — скачивание повреждено" >&2
    rm -f "$NUPKG.part"
    exit 1
  fi
  mv "$NUPKG.part" "$NUPKG"
fi

TMP="$EL/.ort-extract.$$"
rm -rf "$TMP"
mkdir -p "$TMP"
python3 - "$NUPKG" "$TMP" "$RID" <<'PY'
import sys
import zipfile

nupkg, out, rid = sys.argv[1], sys.argv[2], sys.argv[3]
prefixes = ("build/native/include/", f"runtimes/{rid}/native/")
extra = {"LICENSE", "ThirdPartyNotices.txt"}
with zipfile.ZipFile(nupkg) as z:
    for name in z.namelist():
        if name.startswith(prefixes) or name in extra:
            z.extract(name, out)
PY

LIB_SRC="$TMP/runtimes/$RID/native/libonnxruntime.so"
if [ ! -f "$LIB_SRC" ]; then
  echo "❌ В NuGet-пакете нет $LIB_SRC" >&2
  rm -rf "$TMP"
  exit 1
fi
if ! echo "$ORT_SHA256  $LIB_SRC" | sha256sum -c -; then
  echo "❌ SHA256 libonnxruntime.so не совпал" >&2
  rm -rf "$TMP"
  exit 1
fi

mkdir -p "$EL/$ORT/include" "$EL/$ORT/lib"
cp "$TMP/build/native/include/"*.h "$EL/$ORT/include/"
cp "$LIB_SRC" "$EL/$ORT/lib/libonnxruntime.so.1.19.2"
if [ -f "$TMP/runtimes/$RID/native/libonnxruntime_providers_shared.so" ]; then
  cp "$TMP/runtimes/$RID/native/libonnxruntime_providers_shared.so" "$EL/$ORT/lib/"
fi
if [ -f "$TMP/LICENSE" ]; then
  cp "$TMP/LICENSE" "$EL/$ORT/LICENSE"
fi
if [ -f "$TMP/ThirdPartyNotices.txt" ]; then
  cp "$TMP/ThirdPartyNotices.txt" "$EL/$ORT/ThirdPartyNotices.txt"
fi
ln -sf libonnxruntime.so.1.19.2 "$EL/$ORT/lib/libonnxruntime.so.1"
ln -sf libonnxruntime.so.1.19.2 "$EL/$ORT/lib/libonnxruntime.so"
rm -rf "$TMP" "$NUPKG"
echo "✅ OnnxRuntime установлен в $EL/$ORT"
