#!/bin/sh

# early test: ran this on access-rtr, to make sure basic ingest+fwd
# was working ok. (dodges signaling issues, mostly, but interacts with
# client devices basically the same. needs no frrouting instances.)

if ! docker network inspect macnet > /dev/null 2> /dev/null; then
  docker network create -d macvlan --subnet=10.10.1.0/24 --ip-range=10.10.1.16/28 --gateway=10.10.1.1 -o parent=xdn0 macnet
fi

DISCIP=$(dig +short r4v4.amt.akadns.net)

docker create --rm --name amtgw --privileged grumpyoldtroll/amtgw:latest $DISCIP
docker network connect macnet amtgw




