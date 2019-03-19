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

../build-frr.sh

sudo bash -x -e <<EOF
# dhcp for downstream
apt install -y isc-dhcp-server
cp etc/dhcp/dhcpd.conf /etc/dhcp/
systemctl enable isc-dhcp-server.service
systemctl restart isc-dhcp-server.service

# set up forwarding and frr
echo "net.ipv4.ip_forward=1" | tee -a /etc/sysctl.conf
sysctl -w net.ipv4.ip_forward=1

( addgroup --system --gid 92 frr && \
  addgroup --system --gid 85 frrvty && \
  adduser --system --ingroup frr --home /var/opt/frr/ \
     --gecos "FRR suite" --shell /bin/false frr && \
     usermod -a -G frrvty frr ) \
  || echo "frr already set up?"

mkdir -p /var/run/frr && chown frr:frr /var/run/frr
mkdir -p /var/log/frr && chown frr:frr /var/log/frr
mkdir -p /etc/frr
rsync -crvz etc/frr/ /etc/frr/
chown -R frr:frr /etc/frr

if [ -f frr/tools/etc/default/frr ]; then
  cp frr/tools/etc/default/frr /etc/default/frr
fi
cp frr/redhat/frr.service /lib/systemd/system/frr.service
systemctl enable frr.service
systemctl daemon-reload
EOF

ip link show
echo "-------------"
cat /etc/udev/rules.d/$udev_fname
echo "check /etc/udev/rules.d/$udev_fname vs 'ip link show' (above) to ensure correct names were chosen by interface mac"

