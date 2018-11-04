sed -i /etc/cloud/cloud.cfg -e "s/^preserve_hostname: false$/preserve_hostname: true/"

sudo apt install isc-dhcp-server
sudo docker load --input normal-frr.tar

sudo cp etc/dhcp/dhcpd.conf /etc/dhcp/

sudo rm /etc/netplan/50-cloud-init.yaml
sudo cp etc/netplan/10-access-rtr.yaml /etc/netplan/

sudo mkdir -p /var/log/frr/

sudo rsync -crvz etc/frr/ live_frr/
sudo docker run -t -d --net=host --privileged --restart unless-stopped -v /var/log/frr:/var/log/frr -v $PWD/live_frr:/etc/frr --name access-frr frr:latest

sudo docker run -t -d --net=host --privileged --restart unless-stopped -v /var/log/frr:/var/log/frr -v $PWD/live_frr:/etc/frr --name access-frr mip-frr:latest

docker exec -i -t access-frr /usr/bin/vtysh

docker exec -it access-frr /usr/lib/frr/frr-reload.py --reload /etc/frr/frr.conf



ssh -L 10322:10.9.1.3:22 -nNT user@192.168.3.2 &
ssh -p 10322 user@localhost

rsync -crvz --exclude=".*.sw?" -e "ssh -p 10322" access-rtr/etc/ user@localhost:etc/

