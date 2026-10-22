"""Read-only OPD2515 verification after the controlled 103 boot."""
import datetime
import json
import pathlib
import subprocess

import guarded_17 as g


def main():
    prep = g.ROOT / 'root-work/ColorOS17-17.0.0.103-analysis/preparation-20261014_101454'
    p = g.load_plan(prep / 'prepare-plan.json')
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out = prep / ('boot-verification-' + stamp)
    out.mkdir()
    basic = {}
    for prop in ('ro.product.model', 'ro.build.display.id', 'ro.build.version.release',
                 'ro.build.version.sdk', 'ro.boot.slot_suffix', 'sys.boot_completed'):
        r = subprocess.run([str(g.ADB), '-s', g.SERIAL, 'shell', 'getprop', prop],
                           capture_output=True, timeout=8)
        g.require(r.returncode == 0, 'ADB not available')
        basic[prop] = r.stdout.decode('utf-8', 'replace').strip()
    (out / 'basic-state.json').write_text(json.dumps(basic, indent=2), encoding='utf-8')
    g.require(basic['ro.product.model'] == 'OPD2515' and
              basic['ro.build.display.id'] == 'OPD2515_17.0.0.103(CN01)' and
              basic['ro.boot.slot_suffix'] == '_a' and basic['sys.boot_completed'] == '1',
              '103/a has not completed boot; preserve evidence before acting')
    d = g.Device()
    state = d.state()
    g.require(state['uid'] == '0' and state['ksu'] == 'ksud 3.3.1 (uapi: 5)' and state['lkm_live'],
              'Target root not verified')
    g.require(state['kernel'] == '6.12.69-android16-6-g242e1a07f878-ab15865446-4k' and
              state['current'] == 0 and state['next'] == 0, 'Unexpected target kernel/slot')
    expected = {'init_boot_a': g.PATCH_HASH, 'abl_a': g.review.OLD_HASH,
                'boot_a': p['target_images']['boot']['sha256']}
    hashes = {name: d.hash('/dev/block/by-name/' + name) for name in expected}
    g.require(hashes == expected and d.hash(g.EFI + '/ABL_normal.efi') == g.NORMAL_HASH and
              d.hash('/dev/block/by-name/efisp', 290816) == g.review.BDS_HASH,
              'Boot images or EFI differ from reviewed plan')
    for name in ('xbl', 'xbl_config'):
        m = p['target_images'][name]
        value = d.hash('/dev/block/by-name/' + name + '_a', m['bytes'])
        g.require(value == m['sha256'], 'Target low-level firmware changed: ' + name)
        hashes[name + '_a_payload_prefix'] = value
    result = {'decision': '103_A_BOOT_AND_KSU_VERIFIED', 'device_read_only': True,
              'state': state, 'basic': basic, 'hashes': hashes,
              'selinux': d.shell('getenforce'), 'uptime': d.shell('cat /proc/uptime'),
              'ce_available': d.shell('getprop sys.user.0.ce_available'),
              'third_party_modules_paused': not state['enabled_modules'] and not state['queued_modules'],
              'boot_a_successful': bool(d.call(7, 0)), 'boot_a_bootable': bool(d.call(6, 0)),
              'second_reboot_verified': False, 'application_data_verified_by_user': False}
    (out / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'decision': result['decision'], 'version': basic['ro.build.display.id'],
                      'slot': 'a', 'root': state['uid'], 'ksu': state['ksu'],
                      'kernel': state['kernel'], 'merge': state['merge'],
                      'boot_successful': result['boot_a_successful'],
                      'ce_available': result['ce_available'], 'report': str(out)}, ensure_ascii=True, indent=2), flush=True)


if __name__ == '__main__':
    main()
