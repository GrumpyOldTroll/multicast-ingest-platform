#!/bin/bash

set -e
set -x

# build udev rules for mac addresses on this machine.
# Just guess on the order?
did_udev=0
udev_fname=10-access-rtr-inames.rules
if ! ls -l /etc/udev/rules.d/10-access-rtr-inames.rules ; then
  declare -a macs
  idx=0
  for mac in $(ip link show | grep "link/ether" | awk '{print $2;}'); do
    macs[$idx]=$mac
    idx=$(($idx+1))
  done
  if [ "${macs[1]}" = "" ]; then
    echo "not enough interfaces detected (expecting at least 2 for access-rtr)"
    exit 1
  fi
  echo ${macs[0]}
  echo ${macs[1]}
  cat > $udev_fname <<EOF 
# /etc/udev/rules.d/10-access-rtr-inames.rules
# upstream, to internet (thru border)
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="${macs[0]}", NAME="xup0"
# downstream, to local clients
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="${macs[1]}", NAME="xdn0"
EOF
  sudo mv $udev_fname /etc/udev/rules.d/$udev_fname
  sudo udevadm control --reload-rules
  did_udev=1
fi

did_netplan=0
if ! ls -l /etc/netplan/10-access-rtr-init.yaml ; then
  sudo cp etc/netplan/10-access-rtr-init.yaml /etc/netplan/10-access-rtr-init.yaml
  did_netplan=1
fi

if [ "$did_netplan" = "1" ]; then
  sudo netplan apply
fi

sudo bash -x -e <<EOF
# journalctl proved annoyingly large by default
cp -r etc/systemd/journald.conf.d /etc/systemd/

# dhcp for downstream
apt install -y isc-dhcp-server
cp etc/dhcp/dhcpd.conf /etc/dhcp/
cp etc/default/isc-dhcp-server /etc/default/isc-dhcp-server
# dhcp server is not coming up at boot.  applying patch --jake 2020-11
patch -i ${PWD}/../isc-dhcp-server.service.patch -d /lib/systemd/system -p 0
systemctl enable isc-dhcp-server.service
systemctl restart isc-dhcp-server.service
EOF

ip link show
echo "-------------"
cat /etc/udev/rules.d/$udev_fname
echo "check /etc/udev/rules.d/$udev_fname vs 'ip link show' (above) to ensure correct names were chosen by interface mac"

