# SPDX-License-Identifier: GPL-2.0-or-later
PKG_NAME="ksmbd-tools"
PKG_VERSION="3.5.7"
PKG_SHA256="43f18da02499f3dd2c021255b95aa127e83254997502fcdcccb34053461effd1"
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/cifsd-team/ksmbd-tools"
PKG_URL="${PKG_SITE}/archive/refs/tags/${PKG_VERSION}.tar.gz"
PKG_DEPENDS_TARGET="toolchain glib libnl"
PKG_LONGDESC="Userspace configuration and session helper for the Linux ksmbd server"
PKG_TOOLCHAIN="meson"
PKG_MESON_OPTS_TARGET="-Dkrb5=disabled -Drundir=/run -Dsystemdsystemunitdir=/usr/lib/systemd/system"

post_makeinstall_target() {
  # ROCKNIX configures Meson's libexecdir as /usr/lib. Fail packaging if the
  # multicall binary moved, rather than shipping broken service aliases.
  test -x "${INSTALL}/usr/lib/ksmbd.tools" || return 1
  # Slot owns its one share and its opt-in service, rather than the example
  # configuration or upstream automatic service activation.
  rm -rf "${INSTALL}/etc" "${INSTALL}/usr/share/man" "${INSTALL}/usr/lib/systemd"
  rm -f "${INSTALL}/usr/sbin/ksmbd.adduser" "${INSTALL}/usr/sbin/ksmbd.addshare"
  mkdir -p "${INSTALL}/usr/sbin" "${INSTALL}/usr/share/licenses/ksmbd-tools"
  for command in ksmbd.mountd ksmbd.control; do
    ln -sf ../lib/ksmbd.tools "${INSTALL}/usr/sbin/${command}"
  done
  cp "${PKG_BUILD}/COPYING" "${INSTALL}/usr/share/licenses/ksmbd-tools/"
}
