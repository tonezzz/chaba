#!/usr/bin/with-contenv bash
set -eu

cat >/etc/profile.d/zz-chaba-prompt.sh <<'SH'
export PS1='\u@\h:\w\$ '
SH

chmod 0644 /etc/profile.d/zz-chaba-prompt.sh
