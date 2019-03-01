# Multicast Ingest Platform

This is a write-up to describe how to replicate a very simple lab network to ingest multicast traffic from an external source into a network over AMT.  This is a [DRIAD](https://datatracker.ietf.org/doc/draft-ietf-mboned-driad-amt-discovery/)-based proof of concept, using a source-specific AMT relay with no explicit source-specific configuration for the multicast traffic, and no explicit peering with the source network.

This was first presented at IETF 103:

 * [Video](https://www.youtube.com/watch?v=bCy7j-DoGGc&t=56m38s)
 * [Slides](https://datatracker.ietf.org/meeting/103/materials/slides-103-mboned-draft-jholland-mboned-driad-amt-discovery-00)

This write-up describes the full receive network setup using [Free Range Routing](https://frrouting.org/), with a walk-through of the setup process.

## Proof of Concept

The proof of concept itself is just [pimwatch.py](pimwatch.py), which runs:

 * [tcpdump](https://manpages.debian.org/stretch/tcpdump/tcpdump.8.en.html) to watch [PIM](https://tools.ietf.org/html/rfc7761) packets.
 * [dig](https://manpages.debian.org/stretch/dnsutils/dig.1.en.html) for DRIAD's [DNS querying](https://tools.ietf.org/html/draft-ietf-mboned-driad-amt-discovery-01#section-2.2)
 * an [amtgw](https://hub.docker.com/r/grumpyoldtroll/amtgw) docker container to establish tunnels, and
 * the [easiest thing I could find](https://hub.docker.com/r/grumpyoldtroll/iperf-ssm) to send a join/leave through the tunnel.

The rest of the setup is so that there are PIM packets for pimwatch.py to watch and respond to.

If you have a network that can propagate SSM PIM join/leave operations in another way, you can hopefully replicate this using just the ingest-rtr.  You just have to ensure that the RPF within the network for the (S,G)s that come from external networks using DRIAD propagates back to the ingest-rtr (for example, with `ip mroute 0.0.0.0/0 <interface-to-ingest-rtr>`).

## Platform

The devices I've used so far for the multicast ingest platform and its supporting network were the cheapest off-the-shelf microcomputers I've got lying around, suitable for traveling:

![Routers](hackathon103-routers.jpg)

The devices started this life as a default install of [Ubuntu Server 18.04](https://www.ubuntu.com/download/server), selecting only "docker", and sticking with the default for everything else.

![Base Install](base-install-options-screen.jpg)

I expect any setup suitable for FRRouting will work the same, but these instructions include all the commands and configs starting after completing this install and logging into the new machines.

After that, [Free Range Routing](https://frrouting.org/) is launched, and the config in this repo is applied on 3 devices, to bring up this very simple lab network:

![Lab Network](lab-network.png)

Think of this as a simplified version of one of the [examples in the DRIAD spec](https://tools.ietf.org/html/draft-ietf-mboned-driad-amt-discovery-01#section-3.1.1).

## Basic Setup

Normal lab machine setup:

 * add your keys and `chmod 0600 .ssh/authorized_keys`, if desired; maybe visudo to add `user ALL=NOPASSWD: ALL` at the end if you're crazy and/or well-isolated.
 * catch up your updates:

	~~~
	sudo apt update && \
	sudo apt dist-upgrade -y && \
	sudo apt autoremove -y
	~~~

 * prevent your drive from filling up with old kernels over time, since updates are for some reason auto-downloaded but not auto-cleaned by default:

	~~~
	echo 'Unattended-Upgrade::Remove-Unused-Dependencies "true";' | \
	   sudo tee -a /etc/apt/apt.conf.d/50unattended-upgrades
	~~~

 * make docker runnable without sudo:

	~~~
	sudo groupadd docker
	sudo usermod -aG docker $USER
	~~~

 * restart:

   ~~~
	sudo shutdown -r now
	~~~

##Set Up Interfaces

Ubuntu 18 started using interface names that [depend on the hardware](https://www.freedesktop.org/wiki/Software/systemd/PredictableNetworkInterfaceNames/).

There are pros and cons to that, but with the USB-to-Ethernet adapters I'm using, I was getting names that incorporate the MAC address (e.g. "enxc8b3730f34bc"), which makes the network config files non-portable to other systems if used directly.

So this is the portion of the setup where you configure your specific interface names to have the interface names in the network diagram, so that the config files hook up to them properly.  I did it by MAC address with [udev rules](https://wiki.debian.org/udev).

If you want to use the config files from this setup as they stand, you MUST use the exact interface names here, with your own MAC addresses (or other selection criteria).

You can of course configure your system as you like and change the names, but you should make sure to change them in all the other config files also, or your packets are going to have a bad day.

Some claim that changing udev rules also requires `sudo update-initramfs -u' to get it to work, but that was not my experience with Ubuntu 18.04.2.  YMMV, but try that if you're having trouble.

Note the "==" to match rules, and "=" to set the correct interface name at the end of the rules line.

### Border Router

Remember to use your own mac addresses.

~~~
# /etc/udev/rules.d/10-border-rtr-inames.rules
# upstream, to internet
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="00:e0:4c:c1:55:1e", NAME="bup0"
# downstream, to access router
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="c8:b3:73:0f:34:bc", NAME="bdn0"
# reflector, to ingest router
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="c8:b3:73:0f:2f:c4", NAME="brf0"
~~~

Also set up netplan to use these interfaces instead of the auto-configured interface name:

~~~
# /etc/netplan/10-border-rtr-init.yaml
network:
    ethernets:
        bup0:
            addresses: []
            dhcp4: true
            optional: true
            # override nameservers if necessary:
            # nameservers:
            #        addresses: [8.8.8.8,8.8.4.4]
        bdn0:
            addresses: [10.9.1.1/24]
            dhcp4: false
            optional: true
        brf0:
            addresses: [10.8.1.1/24]
            dhcp4: false
            optional: true
    version: 2
~~~

Reboot: `sudo shutdown -r now`

### Access Router

Remember to use your own mac addresses:

~~~
# /etc/udev/rules.d/10-access-rtr-inames.rules
# upstream, to internet through border router
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="00:e0:4c:c1:55:1e", NAME="aup0"
# downstream, to clients
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="c8:b3:73:0f:34:bc", NAME="adn0"
~~~

Also set up netplan to use this instead of the auto-configured interface name:

~~~
# /etc/netplan/10-access-rtr-init.yaml
network:
    ethernets:
        xup0:
            addresses: [10.9.1.3/24]
            dhcp4: false
            nameservers:
                    addresses: [10.9.1.1]
            gateway4: 10.9.1.1
            optional: true
        xdn0:
            addresses: [10.7.1.1/24]
            dhcp4: false
            optional: true
    version: 2
~~~

Notes:

 1. access-rtr uses a static IP and assumes connectivity through the border-rtr.  After applying this config, you'll need to hook up the right topology through the border-rtr or you probably won't have internet.

 2. This configures the border-rtr's DNS server for recursive DNS.  For access-rtr, it's optional, you could instead use 8.8.8.8,8.8.4.4 or something else.

 3. I changed this from adn0 and aup0 to xdn0 and xup0. I _think_ there's a bug, presumably in docker, that has to do with the interface loading order, such that a docker container that tries to use interfaces with a lexically earlier name than 'bridge' has problems hooking up the interfaces properly.  This may need further investigation, but it worked with xup/xdn after NOT working with aup/adn.  Saw the same behavior in a different context.

Reboot: `sudo shutdown -r now`

### Ingest Router

Remember to use your own mac address:

~~~
# /etc/udev/rules.d/10-ingest-rtr-inames.rules
# upstream, to internet through border router
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="00:e0:4c:c1:55:1e", NAME="irf0"
~~~

Also set up netplan to use this instead of the auto-configured interface name.

~~~
# /etc/netplan/10-ingest-rtr-init.yaml
network:
    ethernets:
        irf0:
            addresses: [10.8.1.2/24]
            dhcp4: false
            nameservers:
                    addresses: [10.8.1.1]
            gateway4: 10.8.1.1
            optional: true
    version: 2
~~~

Notes:

 1. ingest-rtr uses a static IP and assumes connectivity through the border-rtr.  After applying this config, you'll need to hook up the right topology through the border-rtr or you probably won't have internet.

 2. this netplan also uses the border router's recursive DNS server.  This lets border-rtr inject DRIAD answers for testing setups that don't have globally deployed DNS zones.

    See this [example DRIAD zone file](configs/border-rtr/etc/bind/zones/reverse.185.212.23.in-addr.arpa.zone).  This example is no longer loaded because now there's now global TYPE260 records for the reverse zone for 23.212.185.x, but earlier testing versions of this setup loaded this zone file in the border-rtr's bind instance, and you may want to configure similar for your own addresses.

Reboot: `sudo shutdown -r now`

#### Side note about interface names

There are other approaches besides the one I'm using for configuring interface names.  It looks like [systemd.link](https://www.freedesktop.org/software/systemd/man/systemd.link.html) is a recommended way to do this, by creating files with names ending in ".link" in /etc/systemd/network or /usr/lib/systemd/network.  However, it didn't work for me on Ubuntu 18.04.2.  Perhaps this will change in the future, and if you're having trouble with the udev rules, consider trying it.

##Get FRR Docker Image

You may want to [build your own](build-frr.md), or you may want to use a pre-built image.  As of this writing, there are a [few options](https://github.com/FRRouting/frr/tree/master/docker) for pre-built images, but [ajones17/frr:latest](https://hub.docker.com/r/ajones17/frr) seems to try to auto-track the latest build, and keeps a history so that old builds can still be accessed if new ones break something by [using a number like "662"](https://hub.docker.com/r/ajones17/frr/tags) instead of "latest".

Regardless of the image you end up using, these setup commands will assume you're using `mip/frr:latest` as the name of your image tag.  If you have a need for a different name, you may have to edit the setup.sh files.  But whatever image you're using, you can tag your image with this name to make the commands work:

~~~
docker pull ajones17/frr:latest
docker tag ajones17/frr:latest mip/frr:latest
~~~

or:

~~~
docker load --input local-build-mip-frr.tar
docker tag local-build-mip-frr:latest mip/frr:latest
~~~

## The Rest of the Config

For the appropriate router you're configuring, run the setup script from the appropriate directory.

Note that these (and the config files they're copying into place) make assumptions about the IPs, the interface names, and the docker image tag on your system, so if you have changed them, be sure to search the config and setup.sh files and make matching changes.

When you're done, there should be a /etc/live-frr with config files and log files being generated there by a running docker container, plus some other systems that get installed and activated.

After a successful install, it should be possible to reboot and come back up gracefully.

Check the scripts for details.

### Border Router

[configs/border-rtr/setup.sh](configs/border-rtr/setup.sh)

~~~
git clone https://github.com/GrumpyOldTroll/multicast-ingest-platform.git
pushd multicast-ingest-platform/configs/border-rtr
sudo ./setup.sh
popd
~~~

### Access Router

[configs/access-rtr/setup.sh](configs/access-rtr/setup.sh)

~~~
git clone https://github.com/GrumpyOldTroll/multicast-ingest-platform.git
pushd multicast-ingest-platform/configs/access-rtr
sudo ./setup.sh
popd
~~~

### Ingest Router

[configs/ingest-rtr/setup.sh](configs/ingest-rtr/setup.sh)

~~~
git clone https://github.com/GrumpyOldTroll/multicast-ingest-platform.git
pushd multicast-ingest-platform/configs/ingest-rtr
sudo ./setup.sh
popd
~~~

## Poke around

The running frr container is basically sort-of like a Cisco IOS command line with different commands, if you run vtysh inside the container:

~~~
docker exec -i -t frr /usr/bin/vtysh
border-rtr3# show ip pim neighbor
Interface         Neighbor    Uptime  Holdtime  DR Pri
bdn0              10.9.1.3  00:02:38  00:01:37       1
brf0              10.8.1.2  00:02:38  00:01:37       1
~~~

If you have to stop and bring back up the routing, it's just repeating the last line from setup.sh to bring it back up, in a way that's stable thru reboot:

~~~
docker stop frr
# ... do stuff ...
# may have to "docker container rm frr"
# in order to load a new one
sudo docker run -t -d --net=host --privileged \
	--restart unless-stopped \
	-v /var/log/frr:/var/log/frr \
	-v /etc/live_frr:/etc/frr \
	--name frr mip/frr:latest
~~~
