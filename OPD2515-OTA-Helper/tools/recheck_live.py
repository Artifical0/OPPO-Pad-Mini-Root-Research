"""Read-only OPD2515 recheck. Saves evidence on the PC; never installs or writes a device."""
import datetime
import os
import hashlib
import json
import pathlib
import re
import shlex
import subprocess

import review

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADB = pathlib.Path(os.environ.get("OPD_ADB", "adb"))
SERIAL = os.environ.get("OPD_SERIAL", "")
ANALYSIS = ROOT / 'root-work/ColorOS17-17.0.0.103-analysis'
PROPS = (
    'ro.product.model', 'ro.product.device', 'ro.build.display.id', 'ro.build.fingerprint',
    'ro.build.version.incremental', 'ro.build.version.release', 'ro.build.version.sdk',
    'ro.build.version.security_patch', 'ro.boot.slot_suffix', 'ro.boot.flash.locked',
    'ro.boot.verifiedbootstate', 'ro.boot.vbmeta.device_state', 'ro.crypto.state',
    'ro.crypto.type', 'ro.virtual_ab.enabled', 'ro.virtual_ab.compression.enabled',
)
PARTS = ('boot', 'init_boot', 'abl', 'xbl', 'xbl_config', 'vbmeta', 'vendor_boot', 'dtbo')


def run(script, root=True, timeout=90, binary=False):
    remote = 'su -c ' + shlex.quote(script) if root else script
    r = subprocess.run([str(ADB), '-s', SERIAL, 'exec-out', remote],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.decode('utf-8', 'replace') + r.stdout[:2048].decode('utf-8', 'replace'))
    return r.stdout if binary else r.stdout.decode('utf-8', 'replace').strip()


def sha_file(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def identity():
    text = run('; '.join('printf "'+p+'="; getprop '+p for p in PROPS), root=False)
    return dict(line.split('=', 1) for line in text.splitlines())


def main():
    before = identity()
    assert before['ro.product.model'] == 'OPD2515', 'Unexpected model'
    assert before['ro.boot.slot_suffix'] in ('_a', '_b'), 'Unknown active slot'
    root_id = run('id')
    assert 'uid=0(' in root_id, 'Root not available'
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    out = ROOT / ('root-work/ota-diagnostics/pre17-live-' + now.strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    report = {'captured_at': now.isoformat(), 'serial': SERIAL, 'phone_read_only': True,
              'identity': before, 'root_identity': root_id, 'active_slot': before['ro.boot.slot_suffix'][-1],
              'partition_hashes': {}, 'firmware_comparison': {}, 'efi': {}, 'errors': []}
    def capture(name, script):
        t = run(script)
        (out/name).write_text(t+'\n', encoding='utf-8')
        return t
    try:
        root_status = capture('root-status.txt', 'id; /data/adb/ksud -V; grep "^kernelsu " /proc/modules; getenforce; uname -r; uptime')
        report['ksu_version'] = re.search(r'ksud[^\n]+', root_status).group(0)
        report['lkm_live'] = bool(re.search(r'^kernelsu .* Live ', root_status, re.M))
        report['kernel'] = next(x for x in root_status.splitlines() if x.startswith('6.12.'))
        bc = capture('bootconfig.txt', 'cat /proc/bootconfig')
        report['bootconfig'] = dict(re.findall(r'^([^=\n]+?)\s*=\s*"([^"\n]*)"', bc, re.M))
        report['bootconfig'] = {k.strip():v for k,v in report['bootconfig'].items()}
        engine = capture('update-engine.txt', '/data/adb/ksu/bin/busybox timeout 4 /system/bin/update_engine_client --follow 2>&1; true')
        statuses = re.findall(r'onStatusUpdate\((UPDATE_STATUS_[A-Z_]+) \((\d+)\)', engine)
        report['update_engine_status'] = statuses[-1][0] if statuses else 'UNKNOWN'
        report['ab_updated_needs_reboot'] = bool(statuses and statuses[-1] == ('UPDATE_STATUS_UPDATED_NEED_REBOOT', '6'))
        capture('bootctl-readonly.txt', 'for c in "hal-info" "get-number-slots" "get-current-slot" "is-slot-bootable 0" "is-slot-bootable 1" "is-slot-marked-successful 0" "is-slot-marked-successful 1"; do echo "$c"; /data/adb/ksu/bin/bootctl $c 2>&1; done; true')
        report['staged_sessions'] = capture('staged-sessions.txt', 'pm list staged-sessions 2>&1; true')
        capture('ota-cache-inventory.txt', 'for d in /data/ota_package /data/ota /data/misc/update_engine; do if [ -d "$d" ]; then echo "$d"; /data/adb/ksu/bin/busybox find "$d" -maxdepth 2 -type f -exec ls -ln "{}" ";"; fi; done')
        capture('update-prefs-readonly.txt', 'for f in /data/misc/update_engine/prefs/*; do if [ -f "$f" ]; then case "$f" in *last-attempt-error*|*update-state*|*current-state*|*target-slot*|*previous-version*|*system-updated*|*boot-id*|*install-completed*|*payload-attempt-number*) echo "$f"; /data/adb/ksu/bin/busybox head -c 2048 "$f"; echo;; esac; fi; done; true')
        capture('modules.txt', 'for d in /data/adb/modules/*; do if [ -f "$d/module.prop" ]; then echo "PATH=$d"; cat "$d/module.prop"; for f in disable remove update; do if [ -e "$d/$f" ]; then echo "FLAG=$f"; fi; done; fi; done')
        capture('ksu-stock-backups.txt', 'for f in /data/adb/ksu/ksu_backup_*; do [ -f "$f" ] && sha256sum "$f"; done; true')
        capture('manager-version.txt', 'dumpsys package me.weishu.kernelsu | grep -E "versionCode=|versionName="; true')
        rows = []
        for part in PARTS:
            for slot in ('a', 'b'):
                p = '/dev/block/by-name/'+part+'_'+slot
                rows.append('if [ -b '+p+' ]; then printf "PART '+part+'_'+slot+' "; blockdev --getsize64 '+p+'; sha256sum '+p+'; readlink -f '+p+'; fi')
        hashes = capture('partition-hashes.txt', '\n'.join(rows))
        for part,size,digest,path,device in re.findall(r'PART (\S+) (\d+)\s+([0-9a-f]{64})\s+(\S+)\s+(\S+)',hashes):
            report['partition_hashes'][part] = {'bytes':int(size), 'sha256':digest, 'path':path, 'device':device}
        assert len(report['partition_hashes']) == len(PARTS)*2, 'Incomplete partition inventory'
        old = json.loads((ROOT/'root-work/ota-diagnostics/B110P02-20261013_092750/image-index.json').read_text(encoding='utf-8-sig'))
        old['init_boot_b'] = {'path':'root-work/patched/KernelSU-v3.3.1-current-b-20261013/current-init_boot_b.img',
                              'sha256':'ca81b0067110ca3cff09b19c9ca15eed46172d4b5adfc5c8db25d79ddb34666f', 'bytes':8388608}
        for part,m in report['partition_hashes'].items():
            m['same_as_latest_record'] = m['sha256'] == old[part]['sha256'] and m['bytes'] == old[part]['bytes']
            p = ROOT/old[part]['path']
            m['existing_backup'] = old[part]['path']
            m['existing_backup_verified'] = p.is_file() and sha_file(p) == old[part]['sha256']
        firmware = review.FIRMWARE_NAMES | {'xbl','xbl_config'}
        stock = json.loads((ANALYSIS/'500-payload-report.json').read_text(encoding='utf-8'))
        target = json.loads((ANALYSIS/'17-payload-report.json').read_text(encoding='utf-8'))
        baseline = {p['name']:p['new'] for p in stock['partitions'] if p['name'] in firmware}
        newer = {p['name']:p['new'] for p in target['partitions'] if p['name'] in firmware}
        active = report['active_slot']
        lines = []
        for name,m in sorted(baseline.items()):
            p = '/dev/block/by-name/'+name+'_'+active
            lines.append('if [ -b '+p+' ]; then printf "FW '+name+' '+str(m['bytes'])+' "; /data/adb/ksu/bin/busybox head -c '+str(m['bytes'])+' '+p+' | sha256sum; else echo "MISSING '+name+'"; fi')
        fw = capture('firmware-prefix-hashes.txt', '\n'.join(lines))
        for name,size,digest in re.findall(r'FW (\S+) (\d+) ([0-9a-f]{64})', fw):
            report['firmware_comparison'][name] = {'prefix_bytes':int(size), 'sha256':digest,
                'matches_500_payload':digest==baseline[name]['sha256'],
                'target17_payload_same_as_500':newer[name]['sha256']==baseline[name]['sha256'] and newer[name]['bytes']==baseline[name]['bytes']}
        report['missing_firmware_partitions'] = re.findall(r'MISSING (\S+)', fw)
        assert len(report['firmware_comparison'])+len(report['missing_firmware_partitions']) == len(baseline)
        capture('efi-tree.txt', '/data/adb/ksu/bin/busybox find /mnt/vendor/persist/efisp -maxdepth 3 -type f -exec ls -ln "{}" ";"')
        efi_dir = out/'efi-readonly-backup'
        efi_dir.mkdir()
        for name in ('ABL_normal.efi','BOOTENTRIES','tools/ENTRIES'):
            remote = '/mnt/vendor/persist/efisp/'+name
            expected = run('sha256sum '+shlex.quote(remote)).split()[0]
            data = run('cat '+shlex.quote(remote), binary=True)
            assert hashlib.sha256(data).hexdigest()==expected==run('sha256sum '+shlex.quote(remote)).split()[0]
            local = efi_dir/name
            local.parent.mkdir(parents=True,exist_ok=True)
            local.write_bytes(data)
            report['efi'][name] = {'sha256':expected,'bytes':len(data)}
        bds = run('/data/adb/ksu/bin/busybox head -c 290816 /dev/block/by-name/efisp',binary=True)
        assert len(bds)==290816
        bds_hash = hashlib.sha256(bds).hexdigest()
        assert bds_hash==run('/data/adb/ksu/bin/busybox head -c 290816 /dev/block/by-name/efisp | sha256sum').split()[0]
        (efi_dir/'BDS-prefix.efi').write_bytes(bds)
        report['efi']['BDS-prefix.efi'] = {'sha256':bds_hash,'bytes':len(bds),'matches_deployed_bds':bds_hash==review.BDS_HASH}
        report['efi']['ABL_normal.efi']['matches_deployed_normal'] = report['efi']['ABL_normal.efi']['sha256']=='6fa5baed02ca05743491afe32e30470f1ec1afb0cca94fe1cd6dbd560242e503'
        after = identity()
        assert after==before, 'Identity changed during capture'
        engine_after = capture('update-engine-after.txt', '/data/adb/ksu/bin/busybox timeout 4 /system/bin/update_engine_client --follow 2>&1; true')
        last = re.findall(r'onStatusUpdate\((UPDATE_STATUS_[A-Z_]+) \((\d+)\)', engine_after)
        assert last==statuses, 'OTA status changed during capture'
        report['capture_complete'] = True
    except Exception as error:
        report['errors'].append(str(error) or type(error).__name__)
        raise
    finally:
        (out/'live-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'out':str(out),'complete':report.get('capture_complete',False),
                          'engine':report.get('update_engine_status'), 'ksu':report.get('ksu_version'),
                          'changed_startup_partitions':[k for k,v in report['partition_hashes'].items() if not v.get('same_as_latest_record')],
                          'firmware_checked':len(report['firmware_comparison']),
                          'firmware_not_500':[k for k,v in report['firmware_comparison'].items() if not v['matches_500_payload']],
                          'errors':report['errors']},ensure_ascii=True),flush=True)


if __name__=='__main__':
    main()
