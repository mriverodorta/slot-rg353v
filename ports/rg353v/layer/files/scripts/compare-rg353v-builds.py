#!/usr/bin/env python3
"""Audit profile package reports and compare actual firmware sizes with a baseline."""
import argparse
import json
from pathlib import Path


def audit_profile(report, policy):
    profile = report['profile']
    if profile not in ('normal', 'development'):
        raise ValueError('Expected a named build profile')
    packages = set(report['packages'])
    required = set(policy['retain'])
    userspace = report['factory_profile'].get('userspace_profile', 'baseline')
    if userspace == 'rg353v-lean-v1':
        checked = report.get('trial_checks', {}).get('userspace', {})
        if checked != {'profile': 'rg353v-lean-v1', 'package_closure': 'passed', 'sdl_build_options': 'passed'}:
            raise ValueError('Lean userspace closure was not validated')
        required -= {'pipewire', 'wireplumber'}
    elif userspace != 'baseline':
        raise ValueError('Unknown userspace profile')
    missing = required - packages
    forbidden = set(policy['shared']['image_remove'] + policy['shared']['network_remove']
                    + policy[profile]['image_remove'] + policy[profile]['network_remove'])
    if userspace == 'rg353v-lean-v1':
        forbidden |= {'pipewire', 'wireplumber'}
    if profile == 'normal':
        forbidden |= {'gdb', 'renderdoc', 'apitrace'}
    elif not {'gdb', 'renderdoc', 'apitrace'} <= packages:
        raise ValueError('Development diagnostics missing')
    if missing or forbidden & packages:
        raise ValueError(f'{profile}: missing runtime {sorted(missing)}; forbidden {sorted(forbidden & packages)}')
    if report['factory_profile']['build_profile'] != profile:
        raise ValueError('Factory profile does not match report')
    return packages


def compare(baseline, reports, policy):
    if len(reports) != 2 or {r['profile'] for r in reports} != {'normal', 'development'}:
        raise ValueError('Compare one Normal and one Development report')
    if reports[0]['factory_profile']['layer_sha256'] != reports[1]['factory_profile']['layer_sha256']:
        raise ValueError('Profiles use different addon layers')
    if reports[0]['factory_profile']['factory_binaries'] != reports[1]['factory_profile']['factory_binaries']:
        raise ValueError('Profiles use different Slot/core binaries')
    results = {}
    for report in reports:
        profile = report['profile']
        if profile not in ('normal', 'development'):
            raise ValueError('Expected a named build profile')
        packages = audit_profile(report, policy)
        if report['factory_profile']['sources'] != baseline['factory_profile']['sources']:
            raise ValueError('Upstream sources changed; this is not a matched comparison')
        def firmware(r):
            values = [v for k, v in r['artifacts'].items() if k.endswith('.tar')]
            if len(values) != 1:
                raise ValueError('Ambiguous firmware inventory')
            return values[0]
        before, after = firmware(baseline), firmware(report)
        if before['payload']['KERNEL'] != after['payload']['KERNEL']:
            raise ValueError('Kernel changed; hardware comparison needs a separate review')
        results[profile] = {
            'cached_build_seconds': report['elapsed_seconds'],
            'package_count': report['package_count'],
            'removed_packages': sorted(set(baseline['packages']) - packages),
            'added_packages': sorted(packages - set(baseline['packages'])),
            'root_regular_bytes': report['root_regular_bytes'],
            'root_saved_bytes': baseline['root_regular_bytes'] - report['root_regular_bytes'],
            'system_bytes': after['payload']['SYSTEM']['bytes'],
            'system_saved_bytes': before['payload']['SYSTEM']['bytes'] - after['payload']['SYSTEM']['bytes'],
            'kernel_unchanged': True,
        }
    return {'schema': 1, 'baseline_package_count': baseline['package_count'],
            'baseline_root_regular_bytes': baseline['root_regular_bytes'],
            'profiles': results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--normal', type=Path)
    p.add_argument('--development', type=Path)
    p.add_argument('--policy', type=Path, default=Path(__file__).resolve().parents[1] / 'ports/rg353v/build-profiles.json')
    p.add_argument('--output', type=Path)
    p.add_argument('--report', type=Path, help='Audit one profile report without a baseline comparison')
    a = p.parse_args()
    read = lambda path: json.loads(path.read_text())
    if a.report:
        if any((a.baseline, a.normal, a.development)):
            p.error('Use --report alone or supply all comparison reports')
        report = read(a.report)
        audit_profile(report, read(a.policy))
        result = {'profile': report['profile'], 'package_audit': 'passed', 'packages': report['package_count']}
    else:
        if not all((a.baseline, a.normal, a.development, a.output)):
            p.error('Comparison requires --baseline, --normal, --development and --output')
        result = compare(read(a.baseline), [read(a.normal), read(a.development)], read(a.policy))
    if a.output:
        a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
