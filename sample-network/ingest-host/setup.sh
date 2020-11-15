#!/bin/bash

# ./setup.sh && sudo reboot
# sudo docker start ingest-rtr

set -e
set -x

# build udev rules for mac addresses on this machine.
# Just guess on the order?
did_udev=0
udev_fname=10-ingest-rtr-inames.rules
if ! ls -l /etc/udev/rules.d/10-ingest-rtr-inames.rules ; then
  declare -a macs
  idx=0
  for mac in $(ip link show | grep "link/ether" | awk '{print $2;}'); do
    macs[$idx]=$mac
    idx=$(($idx+1))
  done
  if [ "${macs[0]}" = "" ]; then
    echo "not enough interfaces detected (expecting at least 1 for ingest-rtr)"
    exit 1
  fi
  echo ${macs[0]}
  cat > $udev_fname <<EOF 
# /etc/udev/rules.d/10-ingest-rtr-inames.rules
# upstream, to internet (thru border)
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="${macs[0]}", NAME="irf0"
EOF
  sudo mv $udev_fname /etc/udev/rules.d/$udev_fname
  sudo udevadm control --reload-rules
  did_udev=1
fi

did_netplan=0
if ! ls -l /etc/netplan/10-ingest-rtr-init.yaml ; then
  sudo cp etc/netplan/10-ingest-rtr-init.yaml /etc/netplan/10-ingest-rtr-init.yaml
  did_netplan=1
fi

if [ "$did_netplan" = "1" ]; then
  sudo netplan apply
fi

sudo bash -x -e <<EOF
# journalctl proved annoyingly large by default
cp -r etc/systemd/journald.conf.d /etc/systemd/

apt-get install -y docker.io
EOF

ip link show
echo "-------------"
cat /etc/udev/rules.d/$udev_fname
echo "check /etc/udev/rules.d/$udev_fname vs 'ip link show' (above) to ensure correct names were chosen by interface mac"

