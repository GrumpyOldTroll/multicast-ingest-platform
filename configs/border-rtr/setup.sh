#!/bin/bash

set -e
set -x

apt install -y bind9 bind9utils bind9-doc

cp etc/bind/named.conf.options /etc/bind/
cp etc/bind/named.conf.local /etc/bind/
mkdir -p /etc/bind/zones
cp etc/bind/zones/* /etc/bind/zones/
mkdir -p /var/log/named
chown bind:bind /var/log/named
ufw allow Bind9

named-checkconf
systemctl restart bind9

cp lib/systemd/system/border-fwd.service /lib/systemd/system/border-fwd.service
systemctl enable border-fwd
systemctl daemon-reload

mkdir -p /var/log/frr/
rsync -crvz etc/frr/ /etc/live_frr/

docker run -t -d --net=host --privileged --restart unless-stopped -v /var/log/frr:/var/log/frr -v /etc/live_frr:/etc/frr --name frr mip/frr:latest

