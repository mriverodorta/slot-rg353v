# SPDX-License-Identifier: GPL-2.0-or-later
PKG_NAME="slot-bootsplash"
PKG_VERSION="1"
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/BrandonKowalski/slot"
PKG_DEPENDS_TARGET="toolchain Python3 systemd"
PKG_DEPENDS_INIT="toolchain libc:init"
PKG_TOOLCHAIN="manual"
PKG_LONGDESC="Slot RG353V boot progress renderer and milestone tracking"

make_target() {
  python3 "${PKG_DIR}/tools/generate-observer-plan.py" "${PKG_DIR}/config/boot-plan.json" observer-plan.h
  ${CC} ${CFLAGS} -I. -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-boot-observer.c" -lsystemd ${LDFLAGS} -o slot-boot-observer
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-recovery-key.c" ${LDFLAGS} -o slot-recovery-key
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-splash.c" -lm ${LDFLAGS} -o slot-splash
  ${HOST_CC} -std=c11 -O2 "${PKG_DIR}/src/slot-splash.c" -lm -o render-host
  ./render-host --rgba 100 complete.rgba
}
make_init() {
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-recovery-key.c" ${LDFLAGS} -o slot-recovery-key-init
  ${CC} ${CFLAGS} -DSLOT_SPLASH_INIT -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-splash.c" -lm ${LDFLAGS} -o slot-splash-init
}
makeinstall_target() {
  mkdir -p "${INSTALL}/usr/bin" "${INSTALL}/usr/share/slot" "${INSTALL}/usr/lib/systemd/system/sysinit.target.wants"
  cp slot-boot-observer "${INSTALL}/usr/bin/slot-boot-observer"
  cp slot-splash "${INSTALL}/usr/bin/slot-splash"
  cp slot-recovery-key "${INSTALL}/usr/bin/slot-recovery-key"
  cp "${PKG_DIR}/scripts/slot-boot-progress" "${INSTALL}/usr/bin/slot-boot-progress"
  chmod 755 "${INSTALL}/usr/bin/slot-boot-progress"
  cp "${PKG_DIR}/scripts/slot-boot-profile" "${INSTALL}/usr/bin/slot-boot-profile"
  chmod 755 "${INSTALL}/usr/bin/slot-boot-profile"
  cp complete.rgba "${INSTALL}/usr/share/slot/boot-complete.rgba"
  cp "${PKG_DIR}/config/boot-plan.json" "${INSTALL}/usr/share/slot/"
  cp "${PKG_DIR}/system.d/slot-boot-progress.service" "${INSTALL}/usr/lib/systemd/system/"
  ln -sf ../slot-boot-progress.service "${INSTALL}/usr/lib/systemd/system/sysinit.target.wants/slot-boot-progress.service"
}
makeinstall_init() {
  mkdir -p "${INSTALL}/usr/bin"
  cp slot-splash-init "${INSTALL}/usr/bin/slot-splash"
  cp slot-recovery-key-init "${INSTALL}/usr/bin/slot-recovery-key"
}
