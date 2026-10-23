#!/bin/sh
set -eu
set -o pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FIXTURE=$1
[ -f "$FIXTURE/NEVER-FLASH.txt" ] || exit 1
BB=${OPD_TEST_BB:-$ROOT/../OPD2515-OTA-Helper/tests/bb.sh}
DEV=$FIXTURE/dev
EFI=$FIXTURE/efi
PKT=$FIXTURE/packet
STATE=$FIXTURE/state
TX=$STATE/transaction
mkdir "$STATE"
. "$ROOT/module/bin/core.sh"
. "$ROOT/module/bin/guards.sh"
printf 'androidboot.slot_suffix = "_b"\nandroidboot.vbmeta.device_state = "unlocked"\n' > "$STATE/bootconfig"
eq "$(boot_value slot_suffix "$STATE/bootconfig")" _b 'raw slot'
eq "$(boot_value vbmeta.device_state "$STATE/bootconfig")" unlocked 'raw unlock'
printf 'androidboot.slot_suffix = "_a"\n' >> "$STATE/bootconfig"
if boot_value slot_suffix "$STATE/bootconfig"; then echo 'FAIL: duplicate raw field'; exit 1; fi

# Parse the real Android service output formats, including ASCII columns.
eq "$(printf "Result: Parcel(00000000 00000001   '........')\n" | parcel_words)" '00000000 00000001' 'inline parcel'
eq "$(printf "Result: Parcel(\n0x00000000: 00000000 00000001 '........'\n)\n" | parcel_words)" '00000000 00000001' 'multiline parcel'
service() {
  case "$3" in
    16777215) echo 'Result: Parcel(00000000 00000001)' ;;
    16777214) cat "$FIXTURE/hal-hash.txt" ;;
    1) echo "Result: Parcel(00000000 $HAL_NEXT)" ;;
    2) echo 'Result: Parcel(00000000 00000001)' ;;
    3) echo 'Result: Parcel(00000000 00000002)' ;;
    4) echo "Result: Parcel(00000000 $HAL_MERGE)" ;;
    6|7) echo 'Result: Parcel(00000000 00000001)' ;;
    *) return 1 ;;
  esac
}
HAL_NEXT=00000000
HAL_MERGE=00000002
ACTIVE=b
hal_guard
echo 'PASS: real inline/multiline HAL parser, pinned interface, slot and snapshot checks'
if hal_read 5; then echo 'FAIL: mutating HAL call'; exit 1; fi
if printf 'Result: Parcel(ffffffff 00000001)\n' | parcel_words | grep -q '^00000000 '; then exit 1; fi

# Substitute hardware only; all plans, ledger/hash checks and transactions are real.
device_guard() { ACTIVE=b; TARGET=a; KSU_VERSION='ksud 3.3.1 (uapi: 5)'; hal_guard; }
modules_guard() { return 0; }
getprop() { case "$1" in ro.build.display.id) echo 'OPD2515_16.0.10.500(CN01)' ;; esac; }
capacity() { file_size "$1"; }
is_block() { [ -f "$1" ]; }
blockdev() { [ "$1" = --setrw ]; }
UE_FIXTURE='onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 1)'
ue_status() { echo "$UE_FIXTURE"; }
expect_blocked() {
  if live_plan_guard > "$STATE/expected.log" 2>&1; then echo "FAIL: $1"; exit 1; fi
  echo "PASS: $1"
}
packet_layout "$PKT/OPD2515-OTA-approved.zip"
if packet_layout "$FIXTURE/duplicate.zip" 2>/dev/null; then echo 'FAIL: duplicate ZIP'; exit 1; fi
if packet_layout "$FIXTURE/path.zip" 2>/dev/null; then echo 'FAIL: path ZIP'; exit 1; fi
live_plan_guard
cp "$PKT/plan.txt" "$STATE/plan.txt"
sed 's/^firmware_names=.*/firmware_names=engineering_cdt/' "$STATE/plan.txt" > "$PKT/plan.txt"
expect_blocked 'incomplete firmware list'
cp "$STATE/plan.txt" "$PKT/plan.txt"
HAL_NEXT=00000001
expect_blocked 'update not activated'
HAL_NEXT=00000000
HAL_MERGE=00000003
expect_blocked 'snapshot merging'
HAL_MERGE=00000002
UE_FIXTURE='onStatusUpdate(UPDATE_STATUS_IDLE (0), 0)'
expect_blocked 'update engine idle'
UE_FIXTURE='onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 1)'
cp "$DEV/tz_a" "$STATE/tz"
printf X | dd of="$DEV/tz_a" bs=1 seek=12 conv=notrunc 2>/dev/null
expect_blocked 'changed target firmware'
cp "$STATE/tz" "$DEV/tz_a"
ACK=APPLY_b
DIRTY=0
if apply_run > "$STATE/ack.log" 2>&1; then exit 1; fi
[ ! -d "$TX" ] && [ "$DIRTY" = 0 ]
ACK=APPLY_a
apply_run
eq "$(cat "$TX/result")" APPLIED 'result'
eq "$(hash_file "$DEV/init_boot_b")" "$(plan_get source_init_boot_hash)" 'source modified'
expect_blocked 'packet cannot be applied twice'
HAL_NEXT=00000001
if rollback_run > "$STATE/rollback-blocked.log" 2>&1; then echo 'FAIL: unsafe rollback'; exit 1; fi
HAL_NEXT=00000000
rollback_run
live_plan_guard
echo 'PASS: source unchanged, target-only writes, readback and state-aware rollback'

# Return failure immediately after a real desktop-file write, then restore.
TX=$STATE/failed-transaction
FAIL_ONCE=1
write_block() {
  write_block_impl "$@" || return 1
  if [ "$FAIL_ONCE" = 1 ]; then FAIL_ONCE=0; return 1; fi
}
if apply_run; then exit 1; fi
[ "$DIRTY" = 1 ] && [ -f "$TX/READY" ]
rollback_run
eq "$(hash_file "$DEV/init_boot_a")" "$(plan_get init_boot_hash)" 'rollback mismatch'
echo 'PASS: interrupted transaction retains and restores verified backups'
echo 'All shell fixtures passed. No device accessed.'
