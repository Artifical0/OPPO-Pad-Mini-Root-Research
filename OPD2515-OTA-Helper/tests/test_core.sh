#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FIXTURE=$1
BB=$ROOT/tests/bb.sh
DEV=$FIXTURE/dev
EFI=$FIXTURE/efi
PKT=$FIXTURE/packet
STATE=$FIXTURE/state-$(date +%s)
TX=$STATE/transaction
mkdir -p "$STATE"
echo "$STATE" > "$FIXTURE/latest-test-state"
. "$ROOT/module/bin/core.sh"
if compare_file_hashes "$STATE/missing-1" "$STATE/missing-2" 'missing inputs' 2>/dev/null; then
  echo 'FAIL: missing files accepted as equal hashes'; exit 1
fi
echo 'PASS: failed reads cannot count as successful readback'
# Only the hardware boundary is substituted. Plans, hashing, writing, verification,
# backups, slot/OTA gates and rollback use the production implementation.
device_guard() { ACTIVE=b; TARGET=a; }
getprop() { case "$1" in ro.build.version.incremental) echo 'OPD2515_16.0.10.500(CN01)' ;; esac; }
UE_FIXTURE='[INFO] onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 1)'
ue_status() { echo "$UE_FIXTURE"; }
capacity() { file_size "$1"; }
blockdev() { case "$1" in --getsize64) file_size "$2" ;; --setrw) return 0 ;; *) return 1 ;; esac; }
is_block() { [ -f "$1" ]; }
expect_blocked() {
  if live_plan_guard > "$STATE/expected-block.log" 2>&1; then echo "FAIL: $1"; exit 1; fi
  echo "PASS: $1"
}
plan_validate
live_plan_guard
echo 'PASS: matching OTA is accepted'
cp "$PKT/plan.txt" "$STATE/policy-original.txt"
sed '/^firmware_policy=/d' "$STATE/policy-original.txt" > "$PKT/plan.txt"
expect_blocked 'missing complete firmware policy blocks writing'
cp "$STATE/policy-original.txt" "$PKT/plan.txt"
printf X | dd of="$DEV/engineering_cdt_a" bs=1 seek=1000 conv=notrunc 2>/dev/null
expect_blocked 'changed firmware beyond five images blocks writing'
cp "$DEV/engineering_cdt_b" "$DEV/engineering_cdt_a"
UE_FIXTURE='[INFO] onStatusUpdate(UPDATE_STATUS_IDLE (0), 0)'
expect_blocked 'idle OTA blocks writing'
UE_FIXTURE='[INFO] onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 1)
[INFO] onStatusUpdate(UPDATE_STATUS_DOWNLOADING (3), 0)'
expect_blocked 'status changing after completed blocks writing'
UE_FIXTURE='[INFO] onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6), 1)'
cp "$PKT/plan.txt" "$STATE/plan-original.txt"
echo 'schema=1' >> "$PKT/plan.txt"
expect_blocked 'duplicate plan fields block writing'
cp "$STATE/plan-original.txt" "$PKT/plan.txt"
sed 's/source_slot=b/source_slot=a/;s/target_slot=a/target_slot=b/' "$STATE/plan-original.txt" > "$PKT/plan.txt"
expect_blocked 'wrong slot blocks writing'
cp "$STATE/plan-original.txt" "$PKT/plan.txt"
cp "$EFI/BOOTENTRIES" "$STATE/entries-original"
echo malicious >> "$EFI/BOOTENTRIES"
expect_blocked 'changed boot menu blocks writing'
cp "$STATE/entries-original" "$EFI/BOOTENTRIES"
printf X | dd of="$DEV/xbl_a" bs=1 seek=1000 conv=notrunc 2>/dev/null
expect_blocked 'different target XBL blocks writing'
cp "$DEV/xbl_b" "$DEV/xbl_a"
cp "$PKT/patched-init_boot.img" "$STATE/patched-original.img"
printf X | dd of="$PKT/patched-init_boot.img" bs=1 seek=5000 conv=notrunc 2>/dev/null
expect_blocked 'modified patch image blocks writing'
cp "$STATE/patched-original.img" "$PKT/patched-init_boot.img"
ACK=APPLY_b
DIRTY=0
if apply_run >/dev/null 2>&1; then echo 'FAIL: wrong acknowledgement accepted'; exit 1; fi
[ ! -d "$TX" ] && [ "$DIRTY" = 0 ]
echo 'PASS: wrong acknowledgement creates no transaction and writes nothing'
ACK=APPLY_a
apply_run
eq "$(cat "$TX/result")" APPLIED 'result not recorded'
eq "$(hash_file "$DEV/init_boot_a")" "$(plan_get patched_hash)" 'patch not applied'
eq "$(hash_file "$DEV/abl_a")" "$(plan_get old_abl_hash)" 'old ABL not applied'
eq "$(hash_file "$EFI/ABL_normal.efi")" "$(plan_get normal_hash)" 'EFI not applied'
eq "$(hash_file "$DEV/init_boot_b")" "$(plan_get source_init_boot_hash)" 'active init changed'
eq "$(hash_file "$DEV/abl_b")" "$(plan_get source_abl_hash)" 'active ABL changed'
echo 'PASS: target-only write, complete readback, active slot unchanged'
expect_blocked 'already applied packet cannot be applied twice'
rollback_run
eq "$(hash_prefix "$DEV/abl_a" "$(plan_get abl_bytes)")" "$(plan_get abl_hash)" 'rollback ABL mismatch'
eq "$(hash_file "$DEV/init_boot_a")" "$(plan_get init_boot_hash)" 'rollback init mismatch'
eq "$(hash_file "$EFI/ABL_normal.efi")" "$(plan_get source_normal_hash)" 'rollback EFI mismatch'
live_plan_guard
echo 'PASS: transaction backup restores original target and EFI'
# Simulate readback failure after the first write and assert DIRTY is armed.
TX=$STATE/transaction-failed
write_block() {
  write_block_impl "$@" || return 1
  if [ "$FAIL_ONCE" = 1 ]; then FAIL_ONCE=0; return 1; fi
}
FAIL_ONCE=1
if apply_run; then echo 'FAIL: write failure ignored'; exit 1; fi
[ "$DIRTY" = 1 ] && [ -f "$TX/READY" ]
echo 'PASS: failed write arms rollback and retains verified backups'
rollback_run
eq "$(hash_file "$DEV/init_boot_a")" "$(plan_get init_boot_hash)" 'failed transaction restore mismatch'
eq "$(hash_file "$EFI/ABL_normal.efi")" "$(plan_get source_normal_hash)" 'failed transaction EFI restore mismatch'
echo 'PASS: rollback after simulated readback failure restores original target'
echo 'All shell fixtures passed. No device was accessed.'
echo PASS > "$STATE/tests-passed"
