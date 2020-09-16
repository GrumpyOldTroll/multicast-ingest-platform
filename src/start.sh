#!/bin/bash
# needs to do the same job as the original start script, but run
# pimwatch forever instead of sleeping forever:
# https://github.com/FRRouting/frr/blob/frr-7.3.1/docker/alpine/docker-start

if [ "$1" = "" ]; then
  echo "the IP of the upstream pim is required as an input argument"
  sleep 1
  exit 1
fi

if !  chown -R frr:frr /etc/frr ; then
  echo "ignoring error with changing ownership in /etc/frr"
fi

my_ip=$(ip addr show | grep eth0 | grep inet | awk '{print $2;}' | cut -f1 -d/)

cd /var/log/frr/
/usr/lib/frr/frrinit.sh start
/usr/bin/python3 /usr/bin/pimwatch.py eth0 ${my_ip} $*

