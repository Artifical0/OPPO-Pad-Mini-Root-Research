#!/system/bin/sh
# Paths are assigned by ota.sh; this file never accepts a block path from a plan.
hash_file() {
  HASH_RAW=$("$BB" sha256sum "$1") || return 1
  HASH_VALUE=${HASH_RAW%% *}
  is_hash "$HASH_VALUE" || return 1
  echo "$HASH_VALUE"
}
hash_prefix() { "$BB" head -c "$2" "$1" | "$BB" sha256sum | "$BB" awk '{print $1}'; }
file_size() { "$BB" stat -c %s "$1"; }
capacity() { blockdev --getsize64 "$1"; }
is_block() { [ -b "$1" ]; }
fail() { echo "ERROR: $*" >&2; return 1; }
eq() { [ "$1" = "$2" ] || fail "$3"; }
is_hash() { [ "${#1}" = 64 ] && ! echo "$1" | "$BB" grep -q '[^0-9a-f]'; }
is_uint() { [ -n "$1" ] && ! echo "$1" | "$BB" grep -q '[^0-9]' && [ "${#1}" -le 10 ]; }
plan_get() { "$BB" awk -F= -v key="$1" '$1==key {print substr($0,length(key)+2)}' "$PKT/plan.txt"; }
plan_validate() {
  [ -f "$PKT/plan.txt" ] || { fail '缺少 plan.txt'; return 1; }
  [ "$(file_size "$PKT/plan.txt")" -le 12000 ] || return 1
  "$BB" awk -F= 'NF!=2 || $1 !~ /^[a-z][a-z0-9_]*$/ || seen[$1]++ {bad=1} END {exit bad}' "$PKT/plan.txt" || { fail '计划格式或重复字段错误'; return 1; }
  eq "$(plan_get schema)" 1 '不支持的计划版本' || return 1
  eq "$(plan_get module_version)" 0.1.0-rc2 '计划与模块版本不符' || return 1
  eq "$(plan_get model)" OPD2515 '型号不符' || return 1
  eq "$(plan_get kmi)" 6.12-android16-6 'KMI 不兼容' || return 1
  eq "$(plan_get firmware_policy)" unchanged_declared_firmware '缺少整包底层固件审查' || return 1
  FW_LIST=$(plan_get firmware_names)
  [ -n "$FW_LIST" ] || { fail '底层固件清单为空'; return 1; }
  echo "$FW_LIST" | "$BB" grep -Eq '^[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*$' || return 1
  for fw in $(echo "$FW_LIST" | "$BB" tr ',' ' '); do
    case "$fw" in engineering_cdt|uefi|aop|aop_config|tz|hyp|modem|bluetooth|dsp|keymaster|spuservice|devcfg|qupfw|uefisecapp|imagefv|shrm|cpucp|featenabler|oplus_sec|splash|cpucp_dtb|soccp_debug|soccp_dcd|pdp|pdp_cdb|tme_seq_patch|hyp_ac_config|multiimgoem|tme_fw|soccp|multiimgqti|tme_config|xbl_ac_config|secretkeeper|tz_ac_config|tz_qti_config|dcp|pvmfw|xbl_ramdump) ;; *) fail '未知固件分区'; return 1 ;; esac
    is_hash "$(plan_get "fw_${fw}_hash")" && is_uint "$(plan_get "fw_${fw}_bytes")" && [ "$(plan_get "fw_${fw}_bytes")" -gt 0 ] || return 1
  done
  case "$(plan_get source_slot):$(plan_get target_slot)" in a:b|b:a) ;; *) fail '槽位错误'; return 1 ;; esac
  for key in source_boot_hash source_init_boot_hash source_abl_hash source_normal_hash entries_hash bds_hash boot_hash init_boot_hash abl_hash xbl_hash xbl_config_hash patched_hash normal_hash old_abl_hash; do
    is_hash "$(plan_get "$key")" || { fail "摘要字段无效：$key"; return 1; }
  done
  for key in boot_bytes init_boot_bytes abl_bytes xbl_bytes xbl_config_bytes boot_capacity init_boot_capacity abl_capacity xbl_capacity xbl_config_capacity patched_bytes normal_bytes old_abl_bytes bds_bytes; do
    is_uint "$(plan_get "$key")" && [ "$(plan_get "$key")" -gt 0 ] || { fail "长度字段无效：$key"; return 1; }
  done
  eq "$(plan_get init_boot_capacity)" 8388608 'init_boot 分区容量异常' || return 1
  eq "$(plan_get patched_bytes)" 8388608 '修补镜像容量异常' || return 1
  eq "$(plan_get old_abl_hash)" 0210487cbc59bdcdb03bb2ee61d9d80fffad8f2ccf35bc7d28d7d9569ad59802 '旧 ABL 不在批准范围' || return 1
  eq "$(plan_get source_abl_hash)" "$(plan_get old_abl_hash)" '当前启动 ABL 不是已验证旧版' || return 1
  eq "$(plan_get bds_bytes)" 290816 'BDS 长度异常' || return 1
  eq "$(plan_get bds_hash)" d485e2de52ef7827fd6c5f6b1c56357da422f9a43f86e10b46a945bd17a4e49c 'BDS 不在批准范围' || return 1
  for pair in 'patched-init_boot.img:patched' 'ABL_normal.efi:normal' 'old-abl.img:old_abl'; do
    name=${pair%:*}; key=${pair#*:}
    [ -f "$PKT/$name" ] || return 1
    eq "$(file_size "$PKT/$name")" "$(plan_get "${key}_bytes")" "文件长度不符：$name" || return 1
    eq "$(hash_file "$PKT/$name")" "$(plan_get "${key}_hash")" "文件摘要不符：$name" || return 1
  done
}
device_guard() {
  eq "$(id -u)" 0 '需要 root' || return 1
  eq "$(getprop ro.product.model)" OPD2515 '设备型号不符' || return 1
  eq "$(getprop ro.boot.flash.locked)" 0 'BL 状态不是解锁' || return 1
  eq "$(getprop ro.boot.verifiedbootstate)" orange '需要 Normal Boot 的真实状态' || return 1
  case "$(uname -r)" in 6.12.*-android16-6-*) ;; *) fail '内核不在支持范围'; return 1 ;; esac
  "$BB" grep -q '^kernelsu .* Live ' /proc/modules || { fail 'KernelSU LKM 未运行'; return 1; }
  /data/adb/ksud -V 2>/dev/null | "$BB" grep -q 'ksud 3.3.0 (uapi: 2)' || { fail '本版只支持 KernelSU 3.3.0'; return 1; }
  case "$(getprop ro.boot.slot_suffix)" in _a) ACTIVE=a; TARGET=b ;; _b) ACTIVE=b; TARGET=a ;; *) fail '无法确认当前槽位'; return 1 ;; esac
  [ -d "$EFI" ] && [ ! -L "$EFI/ABL_normal.efi" ] && [ ! -L "$EFI/BOOTENTRIES" ] || return 1
  eq "$(hash_prefix "$DEV/efisp" 290816)" d485e2de52ef7827fd6c5f6b1c56357da422f9a43f86e10b46a945bd17a4e49c '当前 BDS 已变化' || return 1
  for name in boot init_boot abl xbl xbl_config; do
    is_block "$DEV/${name}_${ACTIVE}" && is_block "$DEV/${name}_${TARGET}" || { fail "缺少物理分区：$name"; return 1; }
  done
}
ue_status() {
  # This vendor's client lacks --status and bootctl lacks the vendor HAL.
  "$BB" timeout 4 /system/bin/update_engine_client --follow 2>&1 || true
}
pending_guard() {
  UE=$(ue_status)
  echo "$UE" | "$BB" grep -q 'onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6),' || { fail 'OTA 尚未完成或无法确认等待重启状态'; return 1; }
  echo "$UE" | "$BB" grep 'onStatusUpdate(' | "$BB" tail -n 1 | "$BB" grep -q 'UPDATE_STATUS_UPDATED_NEED_REBOOT (6)' || { fail 'OTA 状态已经变化'; return 1; }
}
live_plan_guard() {
  plan_validate && device_guard && pending_guard || return 1
  eq "$ACTIVE" "$(plan_get source_slot)" '活动槽位已变化，请重新检查' || return 1
  eq "$TARGET" "$(plan_get target_slot)" '待启动槽位不符' || return 1
  eq "$(getprop ro.build.version.incremental)" "$(plan_get source_build)" '当前系统版本已变化' || return 1
  eq "$(hash_file "$EFI/ABL_normal.efi")" "$(plan_get source_normal_hash)" '当前 Normal EFI 已变化' || return 1
  eq "$(hash_file "$EFI/BOOTENTRIES")" "$(plan_get entries_hash)" '启动菜单已变化' || return 1
  for name in boot init_boot abl; do
    eq "$(hash_file "$DEV/${name}_${ACTIVE}")" "$(plan_get "source_${name}_hash")" "当前 $name 已变化" || return 1
  done
  for name in boot init_boot abl xbl xbl_config; do
    path="$DEV/${name}_${TARGET}"; span=$(plan_get "${name}_bytes"); cap=$(plan_get "${name}_capacity")
    eq "$(capacity "$path")" "$cap" "目标 $name 容量不符" || return 1
    [ "$span" -le "$cap" ] || return 1
    eq "$(hash_prefix "$path" "$span")" "$(plan_get "${name}_hash")" "OTA 后 $name 与已检查固件不符" || return 1
  done
  # Match both active and new XBLs, including authenticated metadata and load segments.
  for name in xbl xbl_config; do
    eq "$(hash_prefix "$DEV/${name}_${ACTIVE}" "$(plan_get "${name}_bytes")")" "$(plan_get "${name}_hash")" "当前和新版 $name 不同" || return 1
  done
  for fw in $(echo "$(plan_get firmware_names)" | "$BB" tr ',' ' '); do
    span=$(plan_get "fw_${fw}_bytes"); expected=$(plan_get "fw_${fw}_hash")
    for suffix in "$ACTIVE" "$TARGET"; do
      path="$DEV/${fw}_$suffix"
      is_block "$path" && [ "$span" -le "$(capacity "$path")" ] || { fail "缺少或无法读取固件分区：$fw"; return 1; }
      eq "$(hash_prefix "$path" "$span")" "$expected" "实际固件 $fw 与已审查完整包不符" || return 1
    done
  done
  eq "$(plan_get old_abl_bytes)" "$(capacity "$DEV/abl_$TARGET")" '旧 ABL 与分区容量不符' || return 1
}
copy_verified() {
  cp "$1" "$2" || return 1
  compare_file_hashes "$1" "$2" "备份校验失败：$1" || return 1
}
compare_file_hashes() {
  HASH_LEFT=$(hash_file "$1") || return 1
  HASH_RIGHT=$(hash_file "$2") || return 1
  eq "$HASH_LEFT" "$HASH_RIGHT" "$3"
}
write_block_impl() {
  is_block "$2" || return 1
  eq "$(file_size "$1")" "$(capacity "$2")" '拒绝不完整分区镜像' || return 1
  blockdev --setrw "$2" || return 1
  "$BB" dd if="$1" of="$2" bs=1048576 conv=fsync || return 1
  sync
  compare_file_hashes "$1" "$2" "写入后校验失败：$2"
}
write_block() { write_block_impl "$@"; }
write_normal() {
  cp "$1" "$EFI/.ota-normal.tmp" || return 1
  chmod 0644 "$EFI/.ota-normal.tmp" || return 1
  compare_file_hashes "$1" "$EFI/.ota-normal.tmp" 'EFI 临时文件不符' || return 1
  mv -f "$EFI/.ota-normal.tmp" "$EFI/ABL_normal.efi" || return 1
  sync
  compare_file_hashes "$1" "$EFI/ABL_normal.efi" 'EFI 写入后校验失败'
}
rollback_run() {
  [ -f "$TX/READY" ] || return 1
  # Confirm the device and slot before restoring a transaction.
  device_guard || return 1
  eq "$ACTIVE" "$(cat "$TX/source-slot")" '回退时活动槽位已改变' || return 1
  [ "$(cat "$TX/target-slot")" = "$TARGET" ] || return 1
  (cd "$TX" && "$BB" sha256sum -c rollback.sha256) || return 1
  write_block "$TX/init_boot.img" "$DEV/init_boot_$TARGET" || return 1
  write_block "$TX/abl.img" "$DEV/abl_$TARGET" || return 1
  write_normal "$TX/ABL_normal.efi" || return 1
  echo ROLLED_BACK > "$TX/result"
}
apply_run() {
  live_plan_guard || return 1
  [ "$ACK" = "APPLY_$TARGET" ] || { fail "需要输入 APPLY_$TARGET"; return 1; }
  mkdir "$TX" || return 1
  copy_verified "$DEV/init_boot_$TARGET" "$TX/init_boot.img" || return 1
  copy_verified "$DEV/abl_$TARGET" "$TX/abl.img" || return 1
  copy_verified "$EFI/ABL_normal.efi" "$TX/ABL_normal.efi" || return 1
  cp "$PKT/plan.txt" "$TX/plan.txt" || return 1
  echo "$ACTIVE" > "$TX/source-slot"; echo "$TARGET" > "$TX/target-slot"
  (cd "$TX" && "$BB" sha256sum init_boot.img abl.img ABL_normal.efi > rollback.sha256) || return 1
  sync
  # Long backups may race an OTA restart. Recheck immediately before writes.
  live_plan_guard || return 1
  echo READY > "$TX/READY"; sync
  echo "$TX" > "$STATE/latest-transaction"; sync
  DIRTY=1
  write_block "$PKT/patched-init_boot.img" "$DEV/init_boot_$TARGET" || return 1
  write_normal "$PKT/ABL_normal.efi" || return 1
  write_block "$PKT/old-abl.img" "$DEV/abl_$TARGET" || return 1
  echo APPLIED > "$TX/result"; sync
  DIRTY=0
  echo "SUCCESS: 已保留目标槽位 $TARGET 的 KSU 和 GBL，逐项校验通过。"
  echo "本模块不执行重启。重启后请确认系统版本、root 和启动菜单。"
}
