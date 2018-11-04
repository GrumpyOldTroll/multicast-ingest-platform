#!/bin/sh

if ! docker network inspect macnet > /dev/null 2> /dev/null; then
  docker network create -d macvlan --subnet=10.10.1.0/24 --ip-range=10.10.1.16/28 --gateway=10.10.1.1 -o parent=enx00000004c71c macnet
fi

DISCIP=$(dig +short r4v4.amt.akadns.net)

docker create --rm --name amtgw --privileged grumpyoldtroll/amtgw:latest $DISCIP
docker network connect macnet amtgw




