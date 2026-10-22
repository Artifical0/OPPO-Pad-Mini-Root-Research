"""Read-only check and PC backup of this exact deferred OPD2515 OTA. No activation."""
import datetime
import json
import pathlib
import xml.etree.ElementTree as ET

import guarded_17 as g

PREP = g.ROOT / 'root-work/ColorOS17-17.0.0.103-analysis/preparation-20261014_101454'
META = '/data/misc/update_engine/prefs/manifest-bytes'
META_HASH = '4ce691fd09e4a62fb1f3104997da7f2d5f417f4f571326466f95486edfbb217d'


def app_state(d):
    xml = d.shell('cat /data/user/0/com.oplus.ota/shared_prefs/state_info.xml')
    return {x.attrib['name']: x.attrib.get('value', x.text or '') for x in ET.fromstring(xml)}


def check_deferred(d):
    s = d.state()
    g.guard_state(s, False)
    a = app_state(d)
    expected = {
        'is_local_update': 'true',
        'local_pkg_target_ota_version': 'OPD2515_17.0.0.103(CN01)',
        'local_pkg_target_ota_version_show': 'OPD2515_17.0.0.103(CN01)',
        'local_pkg_size': '9214591270',
        'update_state': '12',
        'ab_verifying_progress_float': '1.0',
        'ab_update_progress_float': '1.0',
        'ab_finalizing_progress_float': '100.0',
        'ab_update_have_switch_slot_method': 'true',
        'ab_update_should_auto_switch_slot': 'false',
        'local_pkg_wipe': '0',
        'local_pkg_android_version': '17',
        'local_pkg_ota_type': 'AB',
        'real_otaVersion': 'OPD2515_11.C.06_1060_202610061842',
    }
    g.require(all(a.get(k) == v for k, v in expected.items()), 'Updater pending identity/state changed')
    prefs = {k: d.shell('cat /data/misc/update_engine/prefs/' + k)
             for k in ('post-install-succeeded', 'verity-written', 'total-bytes-downloaded')}
    g.require(prefs == {'post-install-succeeded': 'true', 'verity-written': 'true',
                        'total-bytes-downloaded': '9214585085'}, 'Incomplete OTA install')
    g.require(d.hash(META) == META_HASH and int(d.shell('stat -c %s ' + META)) == 327802,
              'Installed authenticated metadata changed')
    g.require(d.call(6, 0) == 0, 'Deferred target a unexpectedly bootable')
    g.require(d.shell('if [ -e /cache/recovery/command ]; then echo PRESENT; else echo ABSENT; fi') == 'ABSENT',
              'Recovery command queued')
    return s, {k: a[k] for k in expected}, prefs


def main():
    g.require(g.sha(pathlib.Path(g.__file__)) == '4a2424163b08d198b0142956aa4bb0cbdb306b86acfb112d996e23983b92dc2e',
              'Reviewed transaction tool changed')
    plan_path = PREP / 'prepare-plan.json'
    g.require(g.sha(plan_path) == '8fe8445438ccc1023393d3824aa1dc32a3967bcbf1842000a70f9a5d71656321',
              'Reviewed plan changed')
    p = g.load_plan(plan_path)
    d = g.Device()
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out = PREP / ('execution-precheck-' + stamp)
    out.mkdir()
    print('READ_ONLY_PRECHECK ' + str(out), flush=True)
    before, app, prefs = check_deferred(d)
    g.inspect(d, p, False)
    print('SOURCE_AND_ASSET_CHECK_PASS', flush=True)
    targets = {}
    for i, (n, m) in enumerate(p['target_images'].items(), 1):
        value = d.hash('/dev/block/by-name/' + n + '_a', m['bytes'])
        g.require(value == m['sha256'], 'Target differs from reviewed 103: ' + n)
        targets[n] = {'bytes': m['bytes'], 'sha256': value, 'matches': True}
        if i % 10 == 0:
            print('TARGET_IMAGES_CHECKED ' + str(i), flush=True)
    g.require(len(targets) == 47, 'Target list incomplete')
    (out / 'target-47-image-check.json').write_text(json.dumps(targets, indent=2), encoding='utf-8')
    verification = d.shell('/system/bin/update_engine_client --verify --metadata=' + META + ' 2>&1')
    g.require('Payload is applicable.' in verification, 'Native payload applicability not confirmed')
    (out / 'native-metadata-verification.txt').write_text(verification, encoding='utf-8')
    d.export(META, out / 'installed-payload-metadata.bin', META_HASH, 327802)
    backups = {}
    for name in ('init_boot', 'abl'):
        remote = '/dev/block/by-name/' + name + '_a'
        digest = d.hash(remote)
        size = int(d.shell('blockdev --getsize64 ' + remote))
        g.require(size == p['target_topology'][name]['bytes'], 'Target capacity changed')
        local = out / ('stock-17-' + name + '_a.img')
        d.export(remote, local, digest, size)
        backups[name] = {'path': str(local), 'sha256': digest, 'bytes': size}
    for name in ('ABL_normal.efi', 'BOOTENTRIES'):
        remote = g.EFI + '/' + name
        digest = d.hash(remote)
        size = int(d.shell('stat -c %s ' + remote))
        local = out / ('source-500-' + name)
        d.export(remote, local, digest, size)
        backups[name] = {'path': str(local), 'sha256': digest, 'bytes': size}
    after, app_after, prefs_after = check_deferred(d)
    g.require(before == after and app == app_after and prefs == prefs_after, 'State changed during precheck')
    record = {'decision': 'DEFERRED_103_AUTHENTICATED_AND_BACKED_UP', 'device_read_only': True,
              'state': after, 'app_state': app, 'prefs': prefs, 'backups': backups,
              'targets_matched': len(targets), 'metadata_sha256': META_HASH,
              'target17_boot_verified': False, 'target17_root_verified': False}
    (out / 'precheck.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(record['decision'], flush=True)


if __name__ == '__main__':
    main()
