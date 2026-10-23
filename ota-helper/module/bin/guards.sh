#!/system/bin/sh
# Only read-only Boot HAL transactions are allowed here. No slot activation.
FIRMWARE_NAMES=aop,aop_config,bluetooth,cpucp,cpucp_dtb,dcp,devcfg,dsp,engineering_cdt,featenabler,hyp,hyp_ac_config,imagefv,keymaster,modem,multiimgoem,multiimgqti,oplus_sec,pdp,pdp_cdb,pvmfw,qupfw,secretkeeper,shrm,soccp,soccp_dcd,soccp_debug,splash,spuservice,tme_config,tme_fw,tme_seq_patch,tz,tz_ac_config,tz_qti_config,uefi,uefisecapp,xbl_ac_config,xbl_ramdump
raw_boot() {
  case "$1" in vbmeta.device_state|verifiedbootstate|slot_suffix) ;; *) return 1 ;; esac
  boot_value "$1" /proc/bootconfig
}
boot_value() {
  "$BB" awk -v key="androidboot.$1" '
    $1==key {
      count++; value=$3
      if (NF!=3 || $2!="=" || value !~ /^"[^"]*"$/) bad=1
      gsub(/^"|"$/, "", value)
    }
    END { if (bad || count!=1) exit 1; print value }
  ' "$2"
}
parcel_words() {
  "$BB" awk '
    /^Result: Parcel\(/ { sub(/^Result: Parcel\(/, ""); inline=1 }
    /^0x[0-9a-f]+:/ { sub(/^0x[0-9a-f]+:[[:space:]]*/, ""); inline=1 }
    inline { sub(/\047.*/, ""); gsub(/[()]/, " ");
      for (i=1;i<=NF;i++) {
        if (length($i)==8 && $i !~ /[^0-9a-f]/) {
          printf "%s%s", sep, $i; sep=" "
        } else { bad=1 }
      }
    }
    { inline=0 }
    END { print ""; exit bad }
  '
}
hal_read() {
  case "$1:${2:-}" in 1:|2:|3:|4:|16777214:|16777215:|6:0|6:1|7:0|7:1) ;; *) return 1 ;; esac
  if [ "$#" = 2 ]; then
    service call android.hardware.boot.IBootControl/default "$1" i32 "$2"
  else
    service call android.hardware.boot.IBootControl/default "$1"
  fi
}
hal_uint() {
  HAL_WORDS=$(hal_read "$@" | parcel_words) || return 1
  echo "$HAL_WORDS" | "$BB" grep -Eq '^00000000 [0-9a-f]{8}$' || return 1
  printf '%d\n' "0x${HAL_WORDS#* }"
}
hal_guard() {
  eq "$(hal_uint 16777215)" 1 'Boot HAL 接口版本变化' || return 1
  HAL_WORDS=$(hal_read 16777214 | parcel_words) || return 1
  # String16, 40 UTF-16 code units: 2400346954240a5de495a1debc81429dd012d7b7.
  eq "$HAL_WORDS" '00000000 00000028 00340032 00300030 00340033 00390036 00340035 00340032 00610030 00640035 00340065 00350039 00310061 00650064 00630062 00310038 00320034 00640039 00300064 00320031 00370064 00370062 00000000' 'Boot HAL 接口摘要变化' || return 1
  eq "$(hal_uint 3)" 2 '不是双槽设备' || return 1
  CURRENT=$(hal_uint 2) && NEXT=$(hal_uint 1) && MERGE=$(hal_uint 4) || return 1
  case "$ACTIVE:$CURRENT:$NEXT" in a:0:0|a:0:1|b:1:0|b:1:1) ;; *) fail '原始槽位与 HAL 不一致'; return 1 ;; esac
  eq "$(hal_uint 6 "$NEXT")" 1 '下次启动槽不可启动' || return 1
  eq "$(hal_uint 7 "$CURRENT")" 1 '当前槽尚未标记启动成功' || return 1
}
device_guard() {
  eq "$(id -u)" 0 '需要 root' || return 1
  eq "$(getprop ro.product.model)" OPD2515 '设备型号不符' || return 1
  eq "$(raw_boot vbmeta.device_state)" unlocked '原始 BL 状态不是解锁' || return 1
  eq "$(raw_boot verifiedbootstate)" orange '需要真实解锁的 Normal Boot' || return 1
  case "$(raw_boot slot_suffix)" in _a) ACTIVE=a; TARGET=b ;; _b) ACTIVE=b; TARGET=a ;; *) fail '无法读取原始槽位'; return 1 ;; esac
  eq "$(getprop ro.boot.slot_suffix)" "_$ACTIVE" '系统与原始槽位不一致' || return 1
  case "$(uname -r)" in 6.12.*-android16-6-*) ;; *) fail 'KMI 不在支持范围'; return 1 ;; esac
  "$BB" grep -q '^kernelsu .* Live ' /proc/modules || { fail 'KernelSU LKM 未运行'; return 1; }
  KSU_VERSION=$(/data/adb/ksud -V 2>/dev/null) || return 1
  case "$KSU_VERSION" in 'ksud 3.3.0 (uapi: 2)'|'ksud 3.3.1 (uapi: 5)') ;; *) fail '只支持 KSU 3.3.0/uapi2 或 3.3.1/uapi5'; return 1 ;; esac
  [ -d "$EFI" ] && [ ! -L "$EFI" ] && [ -f "$EFI/ABL_normal.efi" ] && [ -f "$EFI/BOOTENTRIES" ] && [ ! -L "$EFI/ABL_normal.efi" ] && [ ! -L "$EFI/BOOTENTRIES" ] || return 1
  eq "$(hash_prefix "$DEV/efisp" 290816)" d485e2de52ef7827fd6c5f6b1c56357da422f9a43f86e10b46a945bd17a4e49c 'BDS 不在已验证范围' || return 1
  for name in boot init_boot abl xbl xbl_config; do
    is_block "$DEV/${name}_$ACTIVE" && is_block "$DEV/${name}_$TARGET" || return 1
  done
  NODES=' '
  for name in boot init_boot abl xbl xbl_config; do
    for slot in "$ACTIVE" "$TARGET"; do
      NODE=$("$BB" readlink -f "$DEV/${name}_$slot") || return 1
      case "$NODE" in /dev/block/*) ;; *) fail '分区未解析到物理块设备'; return 1 ;; esac
      case "$NODES" in *" $NODE "*) fail '启动分区映射重复'; return 1 ;; esac
      NODES="$NODES$NODE "
    done
  done
  hal_guard
}
modules_guard() {
  for dir in /data/adb/modules/*; do
    [ -f "$dir/module.prop" ] || continue
    [ "$dir" = /data/adb/modules/opd2515_ota_helper ] && continue
    [ -f "$dir/disable" ] || { fail '先暂停其他模块并重启，再开始 OTA'; return 1; }
  done
  for dir in /data/adb/modules_update/*; do
    [ ! -f "$dir/module.prop" ] || { fail '存在待生效的模块更新，请先重启处理'; return 1; }
  done
}
engine_state() {
  ue_status | "$BB" grep 'onStatusUpdate(' | "$BB" tail -n 1
}
idle_guard() {
  hal_guard || return 1
  eq "$CURRENT" "$NEXT" '下次启动槽已经切换，请先完成更新' || return 1
  eq "$MERGE" 0 '快照尚未合并完成' || return 1
  engine_state | "$BB" grep -q 'UPDATE_STATUS_IDLE (0)' || { fail '导出前更新引擎必须空闲'; return 1; }
}
pending_guard() {
  hal_guard || return 1
  [ "$CURRENT" != "$NEXT" ] || { fail '目标槽尚未由更新器激活；本模块不会切槽'; return 1; }
  case "$MERGE" in 0|2) ;; *) fail '快照状态不允许写入'; return 1 ;; esac
  engine_state | "$BB" grep -q 'UPDATE_STATUS_UPDATED_NEED_REBOOT (6)' || { fail '等待更新引擎进入已完成待重启状态'; return 1; }
}
verify_applied() {
  device_guard && modules_guard && pending_guard || return 1
  eq "$ACTIVE" "$(plan_get source_slot)" '写入时源槽变化' || return 1
  eq "$KSU_VERSION" "$(plan_get ksu_version)" '写入时 KSU 变化' || return 1
  for name in boot init_boot abl; do
    eq "$(hash_file "$DEV/${name}_$ACTIVE")" "$(plan_get source_${name}_hash)" '源分区已变化' || return 1
  done
  eq "$(hash_file "$DEV/init_boot_$TARGET")" "$(plan_get patched_hash)" '目标 KSU 读回不符' || return 1
  eq "$(hash_file "$DEV/abl_$TARGET")" "$(plan_get old_abl_hash)" '目标 ABL 读回不符' || return 1
  eq "$(hash_file "$EFI/ABL_normal.efi")" "$(plan_get normal_hash)" '新版 EFI 读回不符' || return 1
  eq "$(hash_file "$EFI/BOOTENTRIES")" "$(plan_get entries_hash)" '菜单发生变化' || return 1
}
packet_layout() {
  "$BB" unzip -l "$1" | "$BB" awk '
    $1 ~ /^[0-9]+$/ && NF>=4 {
      if (NF!=4) bad=1
      n=$4; size=$1+0
      if (seen[n]++) bad=1
      if (n=="plan.txt") { if (size<1 || size>12000) bad=1 }
      else if (n=="patched-init_boot.img") { if (size!=8388608) bad=1 }
      else if (n=="ABL_normal.efi") { if (size<64 || size>2097152) bad=1 }
      else if (n=="old-abl.img") { if (size!=1048576) bad=1 }
      else bad=1
      count++
    }
    END { exit (bad || count!=4) }
  ' || { fail '保留包成员、长度或重复条目不符合要求'; return 1; }
}
