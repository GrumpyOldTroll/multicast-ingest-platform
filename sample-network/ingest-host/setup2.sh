#!/bin/bash

set -e
set -x

IFACE=irf0
SUBNET=10.9.1.0/24
PIMD=10.9.1.2
BW_MAX_MIBPS=50
JOINFILE=${HOME}/pimwatch/pimwatch.sgs
CBJOINFILE=${HOME}/cbacc/cbacc.sgs
INGEST_VERSION=0.0.5

sudo bash -x -e <<EOF
docker network create --driver bridge amt-bridge
docker network create --driver bridge mcast-native-ingest
docker network create --driver macvlan \
    --subnet=${SUBNET} \
    --opt parent=${IFACE} downstream-mcast

# to improve performance of the first join, pull the amtgw image:
docker pull grumpyoldtroll/amtgw:0.0.4

# run the upstream dummy neighbor
docker run \
    --name upstream-dummy-nbr \
    --privileged \
    --network mcast-native-ingest \
    --log-opt max-size=2m --log-opt max-file=5 \
    -d --restart=unless-stopped \
    grumpyoldtroll/pim-dummy-upstream:0.0.4

# ensure the joinfile is present
mkdir -p $(dirname ${JOINFILE}) && touch ${JOINFILE}

# create pimwatch, attach extra network, and start it
docker create \
    --name pimwatch \
    --privileged \
    --network downstream-mcast --ip ${PIMD} \
    --log-opt max-size=2m --log-opt max-file=5 \
    --restart=unless-stopped \
    -v $(dirname ${JOINFILE}):/etc/pimwatch/ \
    grumpyoldtroll/pimwatch:${INGEST_VERSION} \
      -v \
      --joinfile /etc/pimwatch/$(basename ${JOINFILE}) && \
docker network connect mcast-native-ingest pimwatch && \
docker start pimwatch

mkdir -p $(dirname ${JOINFILE}) && touch ${JOINFILE}
mkdir -p $(dirname ${CBJOINFILE}) && touch ${CBJOINFILE}

# run cbacc
docker run \
    --name cbacc \
    --log-opt max-size=2m --log-opt max-file=5 \
    --network amt-bridge \
    -v $(dirname ${JOINFILE}):/var/run/cbacc-in/ \
    -v $(dirname ${CBJOINFILE}):/var/run/cbacc-out/ \
    --restart=unless-stopped -d \
    grumpyoldtroll/cbacc:${INGEST_VERSION} \
      -v \
      --input-file /var/run/cbacc-in/$(basename ${JOINFILE}) \
      --output-file /var/run/cbacc-out/$(basename ${CBJOINFILE}) \
      --bandwidth ${BW_MAX_MIBPS} \
      --default 12

docker run \
    --name driad-ingest \
    --privileged --network mcast-native-ingest \
    --log-opt max-size=2m --log-opt max-file=5 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v $(dirname $CBJOINFILE):/var/run/ingest/ \
    -d --restart=unless-stopped \
    grumpyoldtroll/driad-ingest:${INGEST_VERSION} \
      --amt amt-bridge \
      --native mcast-native-ingest \
      --joinfile /var/run/ingest/$(basename $CBJOINFILE) -v
EOF

