#!/bin/bash

set -e
set -x

apt install -y isc-dhcp-server
cp etc/dhcp/dhcpd.conf /etc/dhcp
sudo service isc-dhcp-server restart

mkdir -p /var/log/frr/
rsync -crvz etc/frr/ /etc/live_frr/

docker run -t -d --net=host --privileged --restart unless-stopped -v /var/log/frr:/var/log/frr -v /etc/live_frr:/etc/frr --name frr mip/frr:latest

