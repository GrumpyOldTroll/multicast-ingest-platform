#!/bin/sh -e

# send stderr and stdout to a log file
#exec 2> /var/log/etc_config-dum0.log
#exec 1>&2
set -x

IFACE=dum0
/sbin/ip link add dev $IFACE type dummy
/sbin/ip addr add 10.12.1.100/24 dev $IFACE
/sbin/ip link set up dev $IFACE
/bin/bash -c -x "while ! ip link show dev xamtbr0 ; do sleep 1; done"
/sbin/ip link set dev dum0 master xamtbr0
/bin/echo 0 > /sys/devices/virtual/net/xamtbr0/bridge/multicast_snooping
