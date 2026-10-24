# SPDX-License-Identifier: GPL-3.0-or-later
PKG_NAME="slot-startup-profile"
PKG_VERSION="1"
PKG_LICENSE="GPL"
PKG_DEPENDS_TARGET="toolchain busybox slot-rg353v systemd Python3 quirks gpudriver libmali openssl util-linux alsa-lib"
PKG_TOOLCHAIN="manual"

make_target() {
  ${CC} ${CFLAGS} -std=c11 -D_GNU_SOURCE -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-audio-route.c" \
    -lasound ${LDFLAGS} -o slot-audio-route
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-user-setup.c" \
    ${LDFLAGS} -o slot-user-setup
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-graphics-prefetch.c" \
    ${LDFLAGS} -o slot-graphics-prefetch
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-verify.c" \
    -lcrypto ${LDFLAGS} -o slot-verify
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-content-probe.c" \
    -lblkid ${LDFLAGS} -o slot-content-probe
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-sd-library-boot.c" \
    -lblkid ${LDFLAGS} -o slot-sd-library-boot
  ${CC} ${CFLAGS} -std=c11 -O2 -Wall -Wextra -Werror "${PKG_DIR}/src/slot-machine-id-setup.c" \
    ${LDFLAGS} -o slot-machine-id-setup
}

makeinstall_target() {
  mkdir -p "${INSTALL}/usr/bin" "${INSTALL}/usr/lib/systemd/system"
  install -m 755 slot-audio-route "${INSTALL}/usr/bin/slot-audio-route"
  install -m 755 slot-user-setup "${INSTALL}/usr/bin/slot-user-setup"
  install -m 755 slot-verify "${INSTALL}/usr/bin/slot-verify"
  install -m 755 slot-content-probe "${INSTALL}/usr/bin/slot-content-probe"
  install -m 755 slot-sd-library-boot "${INSTALL}/usr/bin/slot-sd-library-boot"
  install -m 755 slot-machine-id-setup "${INSTALL}/usr/bin/slot-machine-id-setup"
  install -m 755 slot-graphics-prefetch "${INSTALL}/usr/bin/slot-graphics-prefetch"
  mkdir -p "${INSTALL}/usr/share/slot/hardware"
  cp "${PKG_DIR}/config/graphics-pages."* "${INSTALL}/usr/share/slot/hardware/"
  cp "${PKG_DIR}/scripts/slot-hardware-start" "${INSTALL}/usr/bin/"
  cp "${PKG_DIR}/scripts/slot-background-start" "${INSTALL}/usr/bin/"
  cp "${PKG_DIR}/scripts/slot-speaker-start" "${INSTALL}/usr/bin/"
  install -m 755 "${PKG_DIR}/scripts/slot-usb-host-start" "${INSTALL}/usr/bin/slot-usb-host-start"
  install -m 755 "${PKG_DIR}/scripts/slot-boot-boost" "${INSTALL}/usr/bin/"
  cp "${PKG_DIR}/scripts/slot-hwdb" "${INSTALL}/usr/bin/"
  mkdir -p "${INSTALL}/usr/lib/slot"
  cp "${PKG_DIR}/scripts/slot-hwdb-cache" "${INSTALL}/usr/lib/slot/hwdb-cache"
  chmod 755 "${INSTALL}/usr/bin/slot-hardware-start" "${INSTALL}/usr/bin/slot-background-start" "${INSTALL}/usr/bin/slot-hwdb"
  chmod 755 "${INSTALL}/usr/bin/slot-speaker-start"
  cp "${PKG_DIR}/system.d/"* "${INSTALL}/usr/lib/systemd/system/"
}

post_install() {
  python3 "${PKG_DIR}/tools/configure-startup.py" --root "${INSTALL}"
  python3 "${PKG_DIR}/tools/configure-userspace.py" --image-root "${INSTALL}"
}
