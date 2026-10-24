#!/usr/bin/env python3
"""Apply checked, device-gated boot hooks to generated project definitions only."""
import argparse,json,re
from pathlib import Path

IDENTITY_HOOK = '''# Slot RG353V persisted identity: validate before PID 1, avoiding a service spawn.
[ ! -e /sysroot/run/slot-machine-id-ready ] || rm -f /sysroot/run/slot-machine-id-ready
if [ -x /sysroot/usr/bin/slot-machine-id-setup ] &&
   /usr/bin/busybox chroot /sysroot /usr/bin/slot-machine-id-setup --check /etc/machine-id /storage/.cache/systemd-machine-id 2>/dev/null; then
  : > /sysroot/run/slot-machine-id-ready
fi

'''

RECOVERY_KEY_HOOK = '''  # Slot RG353V fixed volume input; unknown results retain the original scan.
  if [ "$1" = 114 ] && [ -x /usr/bin/slot-recovery-key ]; then
    if /usr/bin/slot-recovery-key; then
      return 0
    else
      case "$?" in 1) return 1 ;; esac
    fi
  fi
'''

def patch(tree,plan):
    project=tree/'projects/ROCKNIX/packages'
    init=project/'sysutils/busybox/scripts/init'
    original=init.read_text()
    marker='# Slot RG353V graphical boot hooks'
    if marker in original:
        if any(marker not in original for marker in ('# Slot RG353V early splash',
                  '# Slot RG353V persisted identity', '# Slot RG353V fixed volume input')):
            raise RuntimeError('Recompose the Slot boot hooks from official sources')
        return
    names=re.search(r'for BOOT_STEP in \\\n(.*?)\ndo\n',original,re.S)
    if not names:raise RuntimeError('Official init boot-step contract changed')
    steps=names.group(1).replace('\\','').split()
    if steps!=plan['init']:raise RuntimeError('Review changed official init milestones before building')
    old='load_splash() {\n  /usr/bin/rocknix-splash\n'
    new='''load_splash() {
  # Slot RG353V graphical boot hooks
  if [ -x /usr/bin/slot-splash ]; then
    /usr/bin/slot-splash --draw && return
  fi
  /usr/bin/rocknix-splash
'''
    if original.count(old)!=1:raise RuntimeError('Official splash hook changed')
    text=original.replace(old,new)
    old='is_key_pressed() {\n'
    if text.count(old)!=1:raise RuntimeError('Official recovery key-check contract changed')
    text=text.replace(old,old+RECOVERY_KEY_HOOK)
    old='SILENT_OUT=3\n'
    early='''
# Slot RG353V early splash: /dev and /run are ready; storage is not required.
if [ -z "${INIT_UNIT}" ] && [ "${FORCE_RECOVERY}" != yes ] && [ "${DEBUG}" != yes ] && [ -x /usr/bin/slot-splash ]; then
  /usr/bin/slot-splash --draw || :
fi
'''
    if text.count(old)!=1:raise RuntimeError('Official early-init output contract changed')
    text=text.replace(old,old+early)
    old='  StartProgress spinner "Exporting storage as USB MSC... "\n'
    if text.count(old)!=1:raise RuntimeError('Official recovery display contract changed')
    text=text.replace(old,'  [ ! -x /usr/bin/slot-splash ] || /usr/bin/slot-splash --error || :\n'+old)
    old='  ${BOOT_STEP}\n  [ -n "${DEBUG}" ]'
    new='''  [ ! -x /usr/bin/slot-splash ] || /usr/bin/slot-splash --begin "init-${BOOT_STEP}" || :
  ${BOOT_STEP}
  if [ -x /usr/bin/slot-splash ]; then
    /usr/bin/slot-splash --event "init-${BOOT_STEP}" || :
  fi
  [ -n "${DEBUG}" ]'''
    if text.count(old)!=1:raise RuntimeError('Official boot loop changed')
    text=text.replace(old,new)
    old='error() {\n'
    if text.count(old)!=1:raise RuntimeError('Official fatal error handler changed')
    text=text.replace(old,old+'  [ ! -x /usr/bin/slot-splash ] || /usr/bin/slot-splash --error || :\n')
    old='# switch to new sysroot and start real init\n'
    if text.count(old)!=1:raise RuntimeError('Official switch-root contract changed')
    text=text.replace(old,IDENTITY_HOOK+old)
    meta=project/'virtual/initramfs/package.mk'
    m=meta.read_text();needle='for i in ${PKG_DEPENDS_INIT}; do\n'
    if m.count(needle)!=1:raise RuntimeError('Official initramfs dependency contract changed')
    m=m.replace(needle,'# Slot RG353V splash, included in the embedded initramfs.\nif [ "${DEVICE}" = "RK3566" ]; then\n  PKG_DEPENDS_INIT+=" slot-bootsplash:init"\nfi\n\n'+needle)
    init.write_text(text);meta.write_text(m)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('tree',type=Path);p.add_argument('plan',type=Path);a=p.parse_args();patch(a.tree,json.loads(a.plan.read_text()))
