"""Activate this verified deferred OTA through UpdateEngine; never reboot or flash."""
import argparse
import json
import pathlib

import guarded_17 as g
import precheck_deferred_17 as pre


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--precheck', required=True, type=pathlib.Path)
    ap.add_argument('--ack', required=True)
    args = ap.parse_args()
    g.require(args.ack == 'ACTIVATE_AUTHENTICATED_103_NO_REBOOT', 'Activation acknowledgement missing')
    folder = args.precheck.resolve()
    g.require(folder.parent == pre.PREP.resolve() and folder.name.startswith('execution-precheck-20261014_'),
              'Wrong precheck directory')
    record = json.loads((folder / 'precheck.json').read_text(encoding='utf-8'))
    g.require(record['decision'] == 'DEFERRED_103_AUTHENTICATED_AND_BACKED_UP'
              and record['device_read_only'] and record['targets_matched'] == 47
              and record['metadata_sha256'] == pre.META_HASH, 'Incomplete precheck')
    g.require(not (folder / 'activation-started.json').exists(), 'Activation already attempted; inspect state first')
    for m in record['backups'].values():
        f = pathlib.Path(m['path']).resolve()
        g.require(f.parent == folder and f.stat().st_size == m['bytes'] and g.sha(f) == m['sha256'],
                  'Preactivation backup changed')
    d = g.Device()
    before, app, prefs = pre.check_deferred(d)
    g.require(before == record['state'] and app == record['app_state'] and prefs == record['prefs'],
              'State differs from precheck')
    g.require(d.hash('/dev/block/by-name/init_boot_a') == record['backups']['init_boot']['sha256']
              and d.hash('/dev/block/by-name/abl_a') == record['backups']['abl']['sha256'],
              'Stock target images changed')
    verification = d.shell('/system/bin/update_engine_client --verify --metadata=' + pre.META + ' 2>&1')
    g.require('Payload is applicable.' in verification, 'Payload applicability check failed')
    # Stop updater UI callbacks while activation and preservation are being completed.
    d.shell('am force-stop com.oplus.ota')
    latest, _, _ = pre.check_deferred(d)
    g.require(latest == before, 'State changed after pausing updater UI')
    (folder / 'activation-started.json').write_text(json.dumps({'before': before,
        'mechanism': 'native UpdateEngine setShouldSwitchSlotOnReboot with authenticated metadata',
        'updater_ui_force_stopped': True, 'reboot_performed': False}, indent=2), encoding='utf-8')
    print('ACTIVATING_WITH_AUTHENTICATED_METADATA_NO_REBOOT', flush=True)
    try:
        output = d.shell('/data/adb/ksu/bin/busybox timeout 30 /system/bin/update_engine_client '
                         '--switch_slot=true --metadata=' + pre.META + ' --follow 2>&1', timeout=45)
        (folder / 'activation-output.txt').write_text(output, encoding='utf-8')
    finally:
        after = d.state()
        (folder / 'activation-after.json').write_text(json.dumps(after, indent=2), encoding='utf-8')
    g.guard_state(after, True)
    print('UPDATE_ENGINE_READY_FOR_A_NO_REBOOT', flush=True)


if __name__ == '__main__':
    main()
