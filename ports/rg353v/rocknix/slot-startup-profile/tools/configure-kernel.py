#!/usr/bin/env python3
"""Compose opt-in RG353V config and board graph in the generated build tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

PROFILE = 'rg353v-slim-v1'
SYMBOL = re.compile(r'^(?:CONFIG_([A-Z0-9_]+)=(.*)|# CONFIG_([A-Z0-9_]+) is not set)$')
USB_HOST_MODULES = {'USB_EHCI_HCD', 'USB_EHCI_HCD_PLATFORM', 'USB_OHCI_HCD', 'USB_OHCI_HCD_PLATFORM'}
SMB_FEATURES = {'SMB_SERVER': 'm', 'SMBFS': 'm', 'NLS_UCS2_UTILS': 'm',
                'SMB_SERVER_CHECK_CAP_NET_ADMIN': 'y', 'SMB_SERVER_SMBDIRECT': 'n'}


def parse(text):
    result = {}
    for line in text.splitlines():
        match = SYMBOL.fullmatch(line)
        if match:
            result[match[1] or match[3]] = match[2] if match[1] else 'n'
    return result


def optional_file_sharing(base):
    """Every installer profile must be able to provide the optional SMB module."""
    out = []
    present = parse(base)
    for line in base.splitlines():
        match = SYMBOL.fullmatch(line)
        name = (match[1] or match[3]) if match else None
        value = SMB_FEATURES.get(name)
        out.append(line if value is None else
                   f'# CONFIG_{name} is not set' if value == 'n' else f'CONFIG_{name}={value}')
    for name, value in SMB_FEATURES.items():
        if name not in present:
            out.append(f'# CONFIG_{name} is not set' if value == 'n' else f'CONFIG_{name}={value}')
    return '\n'.join(out) + '\n'


def validate(config, policy):
    features = policy.get('optional_features', {})
    if features and features != SMB_FEATURES:
        raise ValueError('Unexpected optional file-sharing kernel features')
    for name, value in features.items():
        if config.get(name, 'n') != value:
            raise ValueError('Optional file-sharing feature mismatch: ' + name)
    for name in policy.get('defer_modules', []):
        if name not in USB_HOST_MODULES or config.get(name) != 'm':
            raise ValueError('Deferred USB host must remain available as a module: ' + name)
    for name, wanted in policy['require'].items():
        if config.get(name, 'n') != wanted:
            raise ValueError(f'Required RG353V feature {name}: expected {wanted}, got {config.get(name)}')
    for names in policy['groups'].values():
        for name in names:
            if config.get(name, 'n') != 'n':
                raise ValueError('Unused feature remains enabled: ' + name)


def compose(base, policy):
    if policy['schema'] != 1 or policy['id'] != PROFILE or policy['kernel'] != '7.0.2':
        raise ValueError('Unsupported kernel profile')
    original = parse(base)
    for name, wanted in policy['require'].items():
        if original.get(name) != wanted:
            raise ValueError('Review changed baseline requirement: ' + name)
    disabled = {name for names in policy['groups'].values() for name in names}
    deferred = set(policy.get('defer_modules', []))
    features = policy.get('optional_features', {})
    if features and features != SMB_FEATURES:
        raise ValueError('Unexpected optional file-sharing kernel features')
    if set(features) & (disabled | policy['require'].keys() | deferred):
        raise ValueError('Optional file-sharing policy overlaps existing hardware policy')
    if not deferred <= USB_HOST_MODULES or deferred & (disabled | policy['require'].keys()):
        raise ValueError('Invalid deferred host module policy')
    if any(original.get(name) not in ('y', 'm') for name in deferred):
        raise ValueError('Review changed USB host baseline')
    if disabled & policy['require'].keys():
        raise ValueError('Removal overlaps required hardware')
    if any(not re.fullmatch('[A-Z0-9_]+', name) for name in disabled):
        raise ValueError('Invalid config symbol')
    out = []
    for line in base.splitlines():
        match = SYMBOL.fullmatch(line)
        name = (match[1] or match[3]) if match else None
        out.append((f'# CONFIG_{name} is not set' if features[name] == 'n' else f'CONFIG_{name}={features[name]}') if name in features else
                   f'# CONFIG_{name} is not set' if name in disabled else
                   f'CONFIG_{name}=m' if name in deferred else line)
    present = parse(base)
    for name, value in features.items():
        if name not in present:
            out.append(f'# CONFIG_{name} is not set' if value == 'n' else f'CONFIG_{name}={value}')
    result = '\n'.join(out) + '\n'
    validate(parse(result), policy)
    return result, {name: original[name] for name in sorted(disabled) if original.get(name, 'n') != 'n'}


def stage(tree, policy_path, profile=None):
    linux = tree/'projects/ROCKNIX/devices/RK3566/linux'
    base_path = linux/'linux.aarch64.conf'
    base = base_path.read_text()
    if 'Linux/arm64 7.0.2 Kernel Configuration' not in base:
        raise ValueError('Review changed kernel version')
    if profile is None:
        text, changed = optional_file_sharing(base), {}
    elif profile == PROFILE:
        text, changed = compose(base, json.loads(policy_path.read_text()))
    else:
        raise ValueError('Unknown kernel profile: ' + profile)
    # Version-specific path wins over the stock config. Always write it,
    # including baseline builds, so the shared builder cannot retain a trial.
    output = linux/'7.0.2/linux.aarch64.conf'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    # Keep the board graph paired with the opt-in HDMI removal. The baseline
    # path deletes our generated patch so a later build cannot inherit it.
    patch = tree/'projects/ROCKNIX/devices/RK3566/patches/linux/1013-slot-rg353v-internal-display.patch'
    radio_patch = patch.with_name('1014-slot-rg353v-rtw88-regulatory.patch')
    policy = json.loads(policy_path.read_text()) if profile else None
    if policy and 'unused_hdmi' in policy['groups']:
        patch.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(policy_path.parent/'rg353v-internal-display.patch', patch)
        shutil.copy2(policy_path.parent/'rg353v-rtw88-regulatory.patch', radio_patch)
    else:
        patch.unlink(missing_ok=True)
        radio_patch.unlink(missing_ok=True)
    # Shared USB networking correctness fix, independent of hardware slimming.
    # Without retrying a busy timer flush, final NCM packets can stay queued.
    ncm_patch = patch.with_name('1015-slot-rg353v-ncm-tx-timer.patch')
    ncm_patch.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).parents[1]/'config/rg353v-ncm-tx-timer.patch', ncm_patch)
    report = {'schema': 1, 'profile': profile or 'baseline', 'base_sha256': hashlib.sha256(base.encode()).hexdigest(),
              'config_sha256': hashlib.sha256(text.encode()).hexdigest(), 'requested_removals': changed,
              'deferred_host_modules': policy.get('defer_modules', []) if policy else [],
              'optional_file_sharing_features': dict(SMB_FEATURES),
              'usb_ncm_tx_retry_patch': hashlib.sha256(ncm_patch.read_bytes()).hexdigest(),
              'candidate_requires_hardware_validation': profile is not None}
    (tree/'.rg353v-kernel.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path)
    parser.add_argument('--policy', type=Path, default=Path(__file__).parents[1]/'config/kernel-slim-v1.json')
    parser.add_argument('--profile', choices=[PROFILE])
    parser.add_argument('--validate', type=Path, help='Validate resolved built .config instead of composing')
    args = parser.parse_args()
    if args.validate:
        validate(parse(args.validate.read_text()), json.loads(args.policy.read_text()))
        print('Resolved RG353V slim kernel requirements passed')
    elif args.tree:
        print(json.dumps(stage(args.tree, args.policy, args.profile), indent=2))
    else:
        parser.error('--tree or --validate required')
