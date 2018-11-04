sudo groupadd docker
sudo useradd -G docker -a user

docker load --input mip-frr.tar
docker pull grumpyoldtroll/amtgw


sudo rm /etc/netplan/50-cloud-init.yaml
sudo cp etc/netplan/40-ingest-rtr.yaml /etc/netplan/

sudo cp etc/config-dum0.sh /etc/config-dum0.sh
sudo cp lib/systemd/system/dummysource.service /lib/systemd/system/
sudo systemctl enable dummysource.service
sudo systemctl daemon-reload
sudo systemctl start dummysource.service

sudo mkdir -p /var/log/frr/

sudo rsync -crvz etc/frr/ live_frr/
docker run -t -d --net=host --privileged --restart unless-stopped -v /var/log/frr:/var/log/frr -v $PWD/live_frr:/etc/frr --name ingest-frr mip-frr:latest


#DISCIP=52.53.177.75
DISCIP=54.67.6.216

Note: network name must be alphabetically later than "bridge"

docker network create --driver macvlan --subnet=10.8.1.0/24 --ip-range=10.8.1.64/26 --gateway=10.8.1.1 -o parent=enp1s0 xamtvlan0


docker create --rm --name amtgw --privileged grumpyoldtroll/amtgw:latest $DISCIP
docker network connect xamtvlan0 amtgw
docker start amtgw


docker network create --driver macvlan --subnet=10.8.1.0/24 --ip-range=10.8.1.128/26 --gateway=10.8.1.1 -o parent=enp1s0 xamtvlan1

docker run -d --network xamtvlan0 --rm --name rx2 grumpyoldtroll/iperf-ssm:latest --server --udp --bind 232.10.10.2 --source 23.212.185.4 --interval 1 --len 1500 --interface eth0



docker exec -i -t ingest-frr /usr/bin/vtysh

docker exec -it ingest-frr /usr/lib/frr/frr-reload.py --reload /etc/frr/frr.conf



ssh -L 10222:10.9.1.2:22 -nNT user@192.168.3.2 &
ssh -p 10222 user@localhost

rsync -crvz --exclude=".*.sw?" -e "ssh -p 10222" ingest-rtr/etc/ user@localhost:etc/

