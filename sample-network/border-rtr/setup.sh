#!/bin/bash

set -e
set -x

# build udev rules for mac addresses on this machine.
# Just guess on the order?
did_udev=0
udev_fname=10-border-rtr-inames.rules
if ! ls -l /etc/udev/rules.d/10-border-rtr-inames.rules ; then
  declare -a macs
  idx=0
  for mac in $(ip link show | grep "link/ether" | awk '{print $2;}'); do
    macs[$idx]=$mac
    idx=$(($idx+1))
  done
  if [ "${macs[2]}" = "" ]; then
    echo "not enough interfaces detected (expecting at least 3 for bdr-rtr)"
    exit 1
  fi
  echo ${macs[0]}
  echo ${macs[1]}
  echo ${macs[2]}
  cat > $udev_fname <<EOF 
# /etc/udev/rules.d/10-border-rtr-inames.rules
# upstream, to internet
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="${macs[0]}", NAME="bup0"
# downstream, to access router
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="${macs[1]}", NAME="bdn0"
# reflector, to ingest router
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="${macs[2]}", NAME="brf0"
EOF
  sudo mv $udev_fname /etc/udev/rules.d/$udev_fname
  sudo udevadm control --reload-rules
  did_udev=1
fi

did_netplan=0
if ! ls -l /etc/netplan/10-border-rtr-init.yaml ; then
  sudo cp etc/netplan/10-border-rtr-init.yaml /etc/netplan/10-border-rtr-init.yaml
  did_netplan=1
fi

if [ "$did_netplan" = "1" ]; then
  sudo netplan apply
fi

sudo bash -x -e <<EOF

# journalctl proved annoyingly large by default
cp -r etc/systemd/journald.conf.d /etc/systemd/

# set up dns server
apt install -y bind9 bind9utils bind9-doc
cp etc/bind/named.conf.options /etc/bind/
cp etc/bind/named.conf.local /etc/bind/
# at the time of this writing, bind.keys in ubuntu server 18.04.02 was wrong.
# had to grab keys from https://www.isc.org/downloads/bind/bind-keys/
cp etc/bind/bind.keys /etc/bind/
mkdir -p /etc/bind/zones
cp etc/bind/zones/* /etc/bind/zones/
mkdir -p /var/log/named
chown bind:bind /var/log/named
ufw allow Bind9
named-checkconf
systemctl restart bind9

# dhcp for downstream and reflector
apt install -y isc-dhcp-server
cp etc/dhcp/dhcpd.conf /etc/dhcp/
cp etc/isc-dhcp-server /etc/default/isc-dhcp-server
# dhcp server is not coming up at boot.  applying patch --jake 2020-11
patch -i ${PWD}/../isc-dhcp-server.service.patch -d /lib/systemd/system -p 0
systemctl enable isc-dhcp-server.service
systemctl restart isc-dhcp-server.service

# upstream nat
cp lib/systemd/system/border-fwd.service /lib/systemd/system/border-fwd.service
systemctl enable border-fwd
systemctl daemon-reload
EOF

ip link show
echo "-------------"
cat /etc/udev/rules.d/$udev_fname
echo "check /etc/udev/rules.d/$udev_fname vs 'ip link show' (above) to ensure correct names were chosen by interface mac"

