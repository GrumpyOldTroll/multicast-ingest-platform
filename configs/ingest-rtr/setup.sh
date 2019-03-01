#!/bin/bash

set -e
set -x

# keep the dummy interface "dum0" up:
cp lib/systemd/system/dummysource.service /lib/systemd/system/
systemctl enable dummysource.service
systemctl daemon-reload
systemctl start dummysource.service

# Note: this network name MUST be alphabetically later than "bridge", or
# something about docker startup gets confused in an unfortunate way.  YMMV
docker network create --driver macvlan --subnet=10.8.1.0/24 --ip-range=10.8.1.64/26 --gateway=10.8.1.1 -o parent=irf0 xamtbr0

mkdir -p /var/log/pimwatch
cp pimwatch.py /usr/bin/pimwatch.py
cp lib/systemd/system/pimwatch.service /lib/systemd/system/
systemctl enable pimwatch.service
systemctl daemon-reload
systemctl start pimwatch.service

mkdir -p /var/log/frr/
rsync -crvz etc/frr/ /etc/live_frr/

docker run -t -d --net=host --privileged --restart unless-stopped -v /var/log/frr:/var/log/frr -v /etc/live_frr:/etc/frr --name frr mip/frr:latest


