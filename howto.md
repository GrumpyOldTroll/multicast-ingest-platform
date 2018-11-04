
# Pull source, make branch

Some useful links:

 * <https://github.com/FRRouting/frr>
 * <http://docs.frrouting.org/projects/dev-guide/en/latest/building-frr-for-alpine.html>

~~~
git clone https://github.com/FRRouting/frr.git
cd frr
git checkout tags/frr-6.1-dev
git checkout -b jake-dev
~~~

# Build docker image

~~~
docker/alpine/build.sh
docker build --rm -f docker/alpine/Dockerfile -t mip-frr:latest .
docker save --output mip-frr.tar mip-frr:latest
~~~

# Load and Run docker images

More useful links:

 * <https://hub.docker.com/r/cumulusnetworks/frrouting/>
 * <http://docs.frrouting.org/projects/dev-guide/en/latest/building-frr-for-alpine.html>

Check configs/*/setup.md

docker exec -i -t border-frr /usr/bin/vtysh
docker exec -i -t access-frr /usr/bin/vtysh
docker exec -i -t ingest-frr /usr/bin/vtysh

ssh 192.168.56.2 "cd github/frr && docker build --rm -f docker/alpine/Dockerfile -t mip-frr:latest . && docker save -o mip-frr.tar mip-frr" && scp 192.168.56.2:github/frr/mip-frr.tar ../mip-frr.tar && scp ../mip-frr.tar user@192.168.3.2:

rsync -crvz --exclude=".*.sw?" -e "ssh -p 10322" ../access-rtr/etc/ user@localhost:etc/ ; rsync -crvz --exclude=".*.sw?" -e "ssh -p 10222" ../ingest-rtr/etc/ user@localhost:etc/ ; rsync -crvz --exclude=".*.sw?" ../border-rtr/etc/ user@192.168.3.2:etc/
ssh -p 10322 user@localhost sudo rsync -crvz etc/frr/ live_frr/ ; ssh -p 10222 user@localhost sudo rsync -crvz etc/frr/ live_frr/ ; ssh user@192.168.3.2 sudo rsync -crvz etc/frr/ live_frr/
ssh -p 10322 user@localhost /snap/bin/docker restart access-frr ; ssh -p 10222 user@localhost /snap/bin/docker restart ingest-frr ; sleep 1 ; ssh user@192.168.3.2 /snap/bin/docker restart border-frr

(discovery for r4v4.amt.akadns.net: 23.202.36.4 or 23.202.37.4)
#r4v4.amt.akadns.net:
#DISCIP=52.53.177.75
DISCIP=54.67.6.216
docker create --rm --name amtgw --privileged grumpyoldtroll/amtgw:latest $DISCIP
docker network connect amtbr amtgw
docker start amtgw

# public feeds

AMT Relays:

162.250.137.254
198.38.23.145

video:

udp://129.174.131.51@233.44.15.9:50001
udp://131.128.93.40@233.56.12.3:5501
udp://131.128.93.40@233.56.12.2:5501
udp://131.128.93.40@233.56.12.1:5501

udp://23.212.185.4@232.10.10.2:12000

dig +short -t TYPE68 4.185.212.23.in-addr.arpa
dig +short -t TYPE68 51.131.174.129.in-addr.arpa
dig +short -t TYPE68 40.93.128.131.in-addr.arpa



DISCIP=162.250.137.254 ; docker create --rm --name amtgw-$DISCIP --privileged grumpyoldtroll/amtgw:latest $DISCIP && docker network connect xamtvlan0 amtgw-$DISCIP && docker start amtgw-$DISCIP

SRC=129.174.131.51 ; DST=233.44.15.9 ; docker run -d --network xamtvlan0 --rm --name join-$SRC-$DST grumpyoldtroll/iperf-ssm:latest --server --udp --bind $DST --source $SRC --interval 1 --len 1500 --interface eth0




