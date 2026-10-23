#!/system/bin/sh
set -u
set -o pipefail
umask 077
MODDIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BB=/data/adb/ksu/bin/busybox
DEV=/dev/block/by-name
EFI=/mnt/vendor/persist/efisp
STATE=/data/adb/opd2515_ota_helper
OUT=/sdcard/Download/OPD2515-OTA
PKT=$STATE/approved
IN=/sdcard/Download/OPD2515-OTA-approved.zip
[ -x "$BB" ] || { echo '缺少 KSU BusyBox' >&2; exit 1; }
. "$MODDIR/bin/core.sh"
. "$MODDIR/bin/guards.sh"
[ "$(id -u)" = 0 ] || exit 1
mkdir -p "$STATE" || exit 1
chmod 0700 "$STATE"
mkdir "$STATE/lock" 2>/dev/null || { echo '已有操作正在进行，请等待完成。' >&2; exit 1; }
DIRTY=0
finish() {
  rc=$?
  trap - EXIT INT TERM
  if [ "$DIRTY" = 1 ]; then
    echo '执行失败，尝试恢复写入前备份。' >&2
    if rollback_run; then echo '原目标分区和 Normal EFI 已恢复。先不要重启。' >&2
    else echo "自动恢复未完成。不要重启。备份位于：$TX" >&2; fi
  fi
  rmdir "$STATE/lock"
  exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT TERM
case "${1:-status}" in
status)
  echo "model=$(getprop ro.product.model)"
  echo "build=$(getprop ro.build.display.id)"
  echo "kernel=$(uname -r)"
  echo "slot=$(getprop ro.boot.slot_suffix)"
  echo "raw_device_state=$(raw_boot vbmeta.device_state)"
  echo "raw_verifiedbootstate=$(raw_boot verifiedbootstate)"
  echo "ota=$(ue_status | "$BB" grep 'onStatusUpdate(' | "$BB" tail -n 1)"
  if device_guard; then echo 'device_check=PASS'; else echo 'device_check=BLOCKED'; fi
  [ ! -f "$STATE/latest-export" ] || echo "export=$(cat "$STATE/latest-export")"
  if [ -f "$PKT/plan.txt" ] && plan_validate; then
    echo "approved_target=$(plan_get target_build)"
    echo "approved_slot=$(plan_get target_slot)"
  fi
  [ ! -f "$STATE/latest-transaction" ] || echo "transaction=$(cat "$STATE/latest-transaction")"
  ;;
export)
  device_guard && modules_guard && idle_guard || exit 1
  eq "$(hash_file "$DEV/abl_$ACTIVE")" 0210487cbc59bdcdb03bb2ee61d9d80fffad8f2ccf35bc7d28d7d9569ad59802 '启动 ABL 已变化' || exit 1
  FREE=$("$BB" df -Pk "$STATE" | "$BB" tail -n 1 | "$BB" awk '{print $4}')
  [ "$FREE" -ge 1048576 ] || { fail '内部存储需至少 1 GiB 可用空间'; exit 1; }
  STAGE=$STATE/export-$(date +%Y%m%d-%H%M%S)
  mkdir "$STAGE" && mkdir -p "$OUT" || exit 1
  for name in boot init_boot abl xbl xbl_config; do
    copy_verified "$DEV/${name}_$ACTIVE" "$STAGE/$name.img" || exit 1
    echo "size_$name=$(capacity "$DEV/${name}_$ACTIVE")" >> "$STAGE/device.txt"
    echo "target_size_$name=$(capacity "$DEV/${name}_$TARGET")" >> "$STAGE/device.txt"
  done
  copy_verified "$EFI/ABL_normal.efi" "$STAGE/ABL_normal.efi" || exit 1
  copy_verified "$EFI/BOOTENTRIES" "$STAGE/BOOTENTRIES" || exit 1
  {
    echo 'schema=2'; echo "ksu_version=$KSU_VERSION"; echo 'raw_device_state=unlocked'; echo 'raw_verifiedbootstate=orange'; echo 'model=OPD2515'; echo "build=$(getprop ro.build.display.id)"
    echo "kernel=$(uname -r)"; echo "active_slot=$ACTIVE"; echo "target_slot=$TARGET"
    echo "bds_hash=$(hash_prefix "$DEV/efisp" 290816)"
  } >> "$STAGE/device.txt"
  device_guard && modules_guard && idle_guard || exit 1
  (cd "$STAGE" && "$BB" sha256sum *.img ABL_normal.efi BOOTENTRIES device.txt > SHA256SUMS) || exit 1
  ARCHIVE=$OUT/$(basename "$STAGE").tar.gz
  "$BB" tar -czf "$ARCHIVE.tmp" -C "$STAGE" . || exit 1
  mv "$ARCHIVE.tmp" "$ARCHIVE" || exit 1
  hash_file "$ARCHIVE" > "$ARCHIVE.sha256"
  echo "$ARCHIVE" > "$STATE/latest-export"
  echo "export=$ARCHIVE"; echo "sha256=$(cat "$ARCHIVE.sha256")"
  # Remove only the explicitly constructed export staging directory after success.
  "$BB" rm -f "$STAGE"/*.img "$STAGE/ABL_normal.efi" "$STAGE/BOOTENTRIES" "$STAGE/device.txt" "$STAGE/SHA256SUMS"
  rmdir "$STAGE"
  ;;
import)
  EXPECTED=${2:-}
  is_hash "$EXPECTED" || { fail '请粘贴电脑报告中的 64 位小写 SHA256'; exit 1; }
  [ -f "$IN" ] && [ ! -L "$IN" ] || { fail "未找到 $IN"; exit 1; }
  [ "$(file_size "$IN")" -le 16777216 ] || exit 1
  STAGE=$STATE/import-$(date +%Y%m%d-%H%M%S)
  mkdir "$STAGE" || exit 1
  cp "$IN" "$STAGE/packet.zip" || exit 1
  eq "$(hash_file "$STAGE/packet.zip")" "$EXPECTED" '保留包 SHA256 不符' || exit 1
  packet_layout "$STAGE/packet.zip" || exit 1
  # Stream fixed names to regular files; archive links are never followed.
  for name in plan.txt patched-init_boot.img ABL_normal.efi old-abl.img; do
    (ulimit -f 18432; "$BB" unzip -p "$STAGE/packet.zip" "$name") > "$STAGE/$name" || exit 1
  done
  PKT=$STAGE
  plan_validate || exit 1
  if [ -d "$STATE/approved" ]; then mv "$STATE/approved" "$STATE/approved-old-$(date +%s)" || exit 1; fi
  mv "$STAGE" "$STATE/approved" || exit 1
  PKT=$STATE/approved
  echo "IMPORTED: $(plan_get target_build) / $(plan_get target_slot)"
  ;;
preview)
  live_plan_guard || exit 1
  echo "READY: $(plan_get source_build) → $(plan_get target_build)"
  echo "活动 $ACTIVE；仅写目标 $TARGET 的 init_boot、abl 及 persist 中的 ABL_normal.efi。"
  echo "确认短语：APPLY_$TARGET"
  ;;
apply)
  ACK=${2:-}
  TX=$STATE/transaction-$(date +%Y%m%d-%H%M%S)
  if apply_run; then
    echo "$TX" > "$STATE/latest-transaction"
  else
    [ ! -f "$TX/READY" ] || DIRTY=1
    exit 1
  fi
  ;;
*) fail '支持 status / export / import SHA256 / preview / apply APPLY_a 或 APPLY_b'; exit 1 ;;
esac
