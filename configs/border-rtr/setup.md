
rsync --exclude=".*.sw?" -crvz etc/ user@192.168.3.2:etc/

sudo apt install bind9 bind9utils bind9-doc

sed -i /etc/cloud/cloud.cfg -e "s/^preserve_hostname: false$/preserve_hostname: true/"
sudo hostnamectl set-hostname border-rtr

<https://www.digitalocean.com/community/tutorials/how-to-configure-bind-as-a-private-network-dns-server-on-ubuntu-18-04>

~~~
sudo docker load --input normal-frr.tar
docker load --input mip-frr.tar

sudo cp etc/bind/named.conf.options /etc/bind/
sudo cp etc/bind/named.conf.local /etc/bind/
sudo mkdir /var/log/named
sudo chown bind:bind /var/log/named
sudo ufw allow Bind9

sudo named-checkconf
sudo systemctl restart bind9

sudo cp etc/netplan/* /etc/netplan/
sudo rm /etc/netplan/50-cloud-init.yaml

sudo cp etc/systemd/system/border-fwd.service /etc/systemd/system/border-fwd.service
sudo systemctl enable border-fwd
sudo systemctl daemon-reload

sudo mkdir -p /var/log/frr/

sudo rsync -crvz etc/frr/ live_frr/
sudo docker run -t -d --net=host --privileged --restart unless-stopped -v /var/log/frr:/var/log/frr -v $PWD/live_frr:/etc/frr --name border-frr mip-frr:latest
~~~

docker exec -i -t border-frr /usr/bin/vtysh

docker exec -it frr /usr/lib/frr/frr-reload.py --reload /etc/frr/frr.conf



sudo iptables -t nat -A POSTROUTING -o enp2s0 -j MASQUERADE
sudo iptables -I FORWARD 1 -i enx20c9d02c4837 -j ACCEPT
sudo iptables -I FORWARD 1 -i enp2s0 -m state --state RELATED,ESTABLISHED -j ACCEPT


