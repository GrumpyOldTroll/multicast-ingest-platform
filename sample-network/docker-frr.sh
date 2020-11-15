#!/bin/bash

set -e

sudo bash -x -e <<EOF
echo "net.ipv4.ip_forward=1" | tee -a /etc/sysctl.conf
sysctl -w net.ipv4.ip_forward=1

apt install -y docker.io

mkdir -p /etc/frr/
cp -r etc/frr/* /etc/frr/

docker create --name frr --restart=unless-stopped --privileged --network host -v /etc/frr:/etc/frr frrouting/frr:v7.3.1
docker start frr
EOF

