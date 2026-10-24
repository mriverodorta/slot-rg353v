# SPDX-License-Identifier: GPL-3.0-or-later
# Official client, scoped to the RG353V Slot profile.
PKG_NAME="slot-wpa-supplicant"
PKG_VERSION="2.12"
PKG_SHA256="08e23937e16d0155e55cab2b51f51fbe10d80a1aa91c4e15442645059b737ef6"
PKG_LICENSE="BSD-3-Clause"
PKG_SITE="https://www.w1.fi/wpa_supplicant/"
PKG_URL="https://w1.fi/releases/wpa_supplicant-${PKG_VERSION}.tar.gz"
PKG_SOURCE_DIR="wpa_supplicant-${PKG_VERSION}"
PKG_DEPENDS_TARGET="toolchain dbus openssl libnl"
PKG_LONGDESC="Wi-Fi authentication backend for the RG353V Slot profile"
PKG_TOOLCHAIN="manual"

make_target() {
  cp "${PKG_DIR}/config/build.config" "${PKG_BUILD}/wpa_supplicant/.config"
  export CFLAGS LDFLAGS
  make -C "${PKG_BUILD}/wpa_supplicant" CC="${CC}" PKG_CONFIG="${PKG_CONFIG}" wpa_supplicant wpa_cli
}

makeinstall_target() {
  mkdir -p "${INSTALL}/usr/lib/slot" "${INSTALL}/usr/bin"
  install -m 755 "${PKG_BUILD}/wpa_supplicant/wpa_supplicant" "${INSTALL}/usr/lib/slot/wpa_supplicant"
  install -m 755 "${PKG_BUILD}/wpa_supplicant/wpa_cli" "${INSTALL}/usr/bin/slot-wpa-cli"
  mkdir -p "${INSTALL}/usr/share/dbus-1/system.d" "${INSTALL}/usr/lib/systemd/system"
  cp "${PKG_BUILD}/wpa_supplicant/dbus/dbus-wpa_supplicant.conf" "${INSTALL}/usr/share/dbus-1/system.d/slot-wpa-supplicant.conf"
  cp "${PKG_DIR}/system.d/slot-wpa-supplicant.service" "${INSTALL}/usr/lib/systemd/system/"
  mkdir -p "${INSTALL}/usr/share/licenses/slot-wpa-supplicant"
  cp "${PKG_BUILD}/COPYING" "${INSTALL}/usr/share/licenses/slot-wpa-supplicant/"
}
