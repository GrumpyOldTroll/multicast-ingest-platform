#!/bin/bash

set -e
set -x

IFACE=irf0
GATEWAY=10.9.1.1
SUBNET=10.9.1.0/24
PIMD=10.9.1.3
INTERNALNET=10.11.1.0/24
INTERNALUPSTREAM=10.11.1.2

sudo bash -x -e <<EOF
# create the networks:
sudo docker network create --driver macvlan --subnet=${SUBNET} --gateway=${GATEWAY} --opt parent=${IFACE} mcast-out

sudo docker network create --driver bridge amt-bridge

sudo docker network create --driver bridge --subnet=${INTERNALNET} mcast-xmit

# create the upstream dummy neighbor
sudo docker run -d --name upstream-dummy-nbr --restart=unless-stopped --privileged --network mcast-xmit --ip ${INTERNALUPSTREAM} grumpyoldtroll/pim-dummy-upstream:latest

# to improve performance of the first join, pull the amtgw image:
sudo docker pull grumpyoldtroll/amtgw:latest

sudo docker create --name ingest-rtr --restart=unless-stopped --privileged --network mcast-out --ip ${PIMD} -v /var/run/docker.sock:/var/run/docker.sock grumpyoldtroll/ingest-rtr:latest ${INTERNALUPSTREAM}
sudo docker network connect mcast-xmit ingest-rtr

sudo docker start ingest-rtr
EOF

