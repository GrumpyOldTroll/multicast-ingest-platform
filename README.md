# Multicast Ingest Platform

This is a write-up to describe how to replicate a simple but complete multicast-capable lab network with multiple routers that can ingest multicast traffic from an external source into a network over AMT.

This is a [DRIAD](https://datatracker.ietf.org/doc/draft-ietf-mboned-driad-amt-discovery/)-based proof of concept, using a source-specific AMT relay with no explicit source-specific configuration for the multicast traffic, and no explicit peering with the source network.

This was first presented at IETF 103:

 * [Video](https://www.youtube.com/watch?v=bCy7j-DoGGc&t=56m38s)
 * [Slides](https://datatracker.ietf.org/meeting/103/materials/slides-103-mboned-draft-jholland-mboned-driad-amt-discovery-00)

This write-up describes the full receive network setup using [Free Range Routing](https://frrouting.org/), with a walk-through of the setup process.

## Proof of Concept

The proof of concept itself is just [pimwatch.py](configs/ingest-rtr/pimwatch.py), which runs:

 * [tcpdump](https://manpages.debian.org/stretch/tcpdump/tcpdump.8.en.html) to watch [PIM](https://tools.ietf.org/html/rfc7761) packets.
 * [dig](https://manpages.debian.org/stretch/dnsutils/dig.1.en.html) for DRIAD's [DNS querying](https://tools.ietf.org/html/draft-ietf-mboned-driad-amt-discovery-01#section-2.2)
 * an [amtgw](https://hub.docker.com/r/grumpyoldtroll/amtgw) docker container to establish tunnels, and
 * the [easiest thing I could find (iperf-ssm)](https://hub.docker.com/r/grumpyoldtroll/iperf-ssm) to send a join/leave through the tunnel.

The rest of the setup is so that there are PIM packets for pimwatch.py to watch and respond to.

If you have a network that can propagate SSM PIM join/leave operations in another way, you can hopefully replicate this using just the ingest-rtr.  You just have to ensure that the RPF within the network for the (S,G)s that come from external networks using DRIAD propagates back to the ingest-rtr (for example, with `ip mroute 0.0.0.0/0 <interface-to-ingest-rtr>`).

## Platform

The devices I've used so far for the multicast ingest platform and its supporting network were the cheapest off-the-shelf microcomputers I've got lying around, suitable for traveling:

![Routers](hackathon103-routers.jpg)

The devices started this life as a default install of [Ubuntu Server 18.04](https://www.ubuntu.com/download/server).  You can stick with the defaults, or select the "docker" snap (or not--it'll be installed by the setup script on ingest-rtr).

![Base Install](base-install-options-screen.jpg)

I expect any setup suitable for FRRouting will work the same, but these instructions include all the commands and configs starting after completing this install and logging into the new machines.

After that, [Free Range Routing](https://frrouting.org/) is launched, and the config in this repo is applied on 3 devices, to bring up this very simple lab network:

![Lab Network](lab-network.png)

Think of this as a simplified version of one of the [examples in the DRIAD spec](https://tools.ietf.org/html/draft-ietf-mboned-driad-amt-discovery-01#section-3.1.1).

## Basic Setup

Normal lab machine setup:

 * add your keys and `chmod 0600 .ssh/authorized_keys`, if desired; maybe visudo to add `user ALL=NOPASSWD: ALL` at the end if you're crazy and/or well-isolated.

 * catch up your updates
 * prevent your drive from filling up with old kernels over time, since updates are for some reason auto-downloaded but not auto-cleaned by default:
 * restart

	~~~
	sudo bash -x -e <<EOF
	apt update
	apt dist-upgrade -y
	apt autoremove -y
	echo 'Unattended-Upgrade::Remove-Unused-Dependencies "true";' | \
	   tee -a /etc/apt/apt.conf.d/50unattended-upgrades 
	EOF
	~~~

## Setup Scripts

The basic process for each of the routers is the same, from the different directories:

 * `configs/border-rtr/`
 * `configs/access-rtr/`
 * `configs/ingest-rtr/`

~~~
git clone https://github.com/GrumpyOldTroll/multicast-ingest-platform.git
cd multicast-ingest-platform/
# either border-rtr, access-rtr, or ingest-rtr
cd configs/border-rtr/
./setup.sh
sudo shutdown -r now
~~~

After a successful install, it should be possible to reboot and come back up gracefully.

For ease of config, I've got dhcp client on for ingest-rtr and access-rtr running on the upstream interface, so it still should work ok after configuring it, whether or not you're running through the border-rtr and have the topology set up, in theory.

Check the scripts for details.  In all 3 cases, it builds frr locally from source and installs it, and turns on ip forwarding.  Extra details:

 * [border-rtr](configs/border-rtr/setup.sh):
  * runs dhcp client upstream
  * runs dhcp server on both downstream interfaces (mainly for convenience during setup of the other 2, and could reasonably be turned off after they're up)
  * runs a dns server
  * runs a NAT with iptables for traffic from downstream
 * [access-rtr](configs/access-rtr/setup.sh):
  * runs dhcp server downstream
  * uses border-rtr's dns server
 * [ingest-rtr](configs/ingest-rtr/setup.sh):
  * runs pimwatch.py, the DRIAD implementation hack (launches docker containers based on PIM packets it sees)

## Interface Setup

### Interface Names

This section is about the cryptic messages you should hopefully get about interface names and mac addresses at the end of setup.sh.

Ubuntu 18 started using interface names that [depend on the hardware](https://www.freedesktop.org/wiki/Software/systemd/PredictableNetworkInterfaceNames/).

There are pros and cons to that, but with the USB-to-Ethernet adapters I'm using, I was getting names that incorporate the MAC address (e.g. "enxc8b3730f34bc"), which makes the network config files non-portable to other systems if used directly.

I'm working around this by MAC address with [udev rules](https://wiki.debian.org/udev).  I'm auto-generating the mac addresses from the output of `ip link show`, so things might go wrong if there's any unexpected slight mismatches.

If you want to use the config files from this setup as they stand, you MUST use the exact interface names here, with your own MAC addresses (or other selection criteria).

You can of course configure your system as you like and change the names, but you should make sure to change them in all the other config files also, or your packets are going to have a bad day.

Some claim that changing udev rules also requires `sudo update-initramfs -u' to get it to work, but that was not my experience with Ubuntu 18.04.2.  YMMV, but try that if you're having trouble.

The setup.sh scripts attempt to generate these files, but you should check them to make sure the interfaces are the ones you want, and edit them if necessary.

 * /etc/udev/rules.d/10-border-rtr-inames.rules
 * /etc/udev/rules.d/10-access-rtr-inames.rules
 * /etc/udev/rules.d/10-ingest-rtr-inames.rules

The interface names to configure are:

 * border-rtr:
   * bup0: border-rtr upstream
   * bdn0: border-rtr downstream
   * brf0: border-rtr reflector
 * access-rtr:
   * xup0: access-rtr upstream
   * xdn0: access-rtr downstream
 * ingest-rtr:
   * irf0: ingest-rtr reflector

#### Example

This is an example of what one of the udev rules might look like.

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

#### Side note on alternate approachs

There are other approaches besides the one I'm using for configuring interface names.  It looks like [systemd.link](https://www.freedesktop.org/software/systemd/man/systemd.link.html) is a recommended way to do this, by creating files with names ending in ".link" in /etc/systemd/network or /usr/lib/systemd/network.  However, it didn't work for me on Ubuntu 18.04.2.  Perhaps this will change in the future, and if you're having trouble with the udev rules, consider trying it.

#### Side note on name choice

In the access-rtr, I'm using xdn0 and xup0 instead of adn0 and aup0.

I _think_ there's a bug, presumably in docker, that has to do with the interface loading order, such that a docker container that tries to use interfaces with a lexically earlier name than 'bridge' has problems hooking up the interfaces properly.

This may need further investigation, but when I was running frr inside a docker container, it worked with xup/xdn after NOT working with aup/adn.  Saw the same behavior one other time in a different context, but haven't dug in well enough to make a solid bug report.

### Netplan

The script also sets up netplan to use these interfaces instead of the auto-configured interface name:

 * [/etc/netplan/10-border-rtr-init.yaml](config/border-rtr/etc/netplan/10-border-rtr-init.yaml)
 * [/etc/netplan/10-access-rtr-init.yaml](config/access-rtr/etc/netplan/10-access-rtr-init.yaml)
 * [/etc/netplan/10-ingest-rtr-init.yaml](config/ingest-rtr/etc/netplan/10-ingest-rtr-init.yaml)

These should match up with the network diagram, but if you've messed with anything, you'll want to make sure to update these.

Notes:

 1. access-rtr and ingest-rtr use a static IP and assumes connectivity through the border-rtr.  border-rtr offers dhcp server through both interfaces, so it _should_ work to just plug in the upstream connection through border-rtr while configuring access-rtr and ingest-rtr, and then if everything's hooked up right, it'll all be fine when it reboots.  But sometimes there's trouble.

 2. the access-rtr and ingest-rtr netplan use the border router's recursive DNS server.  This lets border-rtr inject DRIAD answers for testing setups that don't have globally deployed DNS zones.

    See this [example DRIAD zone file](configs/border-rtr/etc/bind/zones/reverse.185.212.23.in-addr.arpa.zone).  This example is no longer loaded because now there's now global TYPE260 records for the reverse zone for 23.212.185.x, but earlier testing versions of this setup loaded this zone file in the border-rtr's bind instance, and you may want to configure similar for your own addresses.

## Poke around

Once it's all set up, you should be able to plug in a client downstream of the access (it should get an address automatically with dhcp), and have it do a SSM join (for instance with [iperf-ssm](https://github.com/GrumpyOldTroll/iperf-ssm)), and see pimwatch on border-rtr react by trying to find an AMT relay, and subscribing to traffic if possible.

For example, this should work if you've got docker and my sender is still alive and properly configured (you get about 1 packet per second, and it's a good way to watch the pcaps from various points on the network):

~~~
docker run -it --rm --name rx2 grumpyoldtroll/iperf-ssm:latest --server --udp --bind 232.10.1.1 --source 23.212.185.5 --interval 1 --len 1500 --interface eth0
~~~

The frr config is in /etc/frr/.

The running frr process is basically sort-of like a Cisco IOS command line with slightly different commands, if you run vtysh to connect to it:

~~~
sudo /usr/bin/vtysh
border-rtr# show ip pim neighbor
Interface         Neighbor    Uptime  Holdtime  DR Pri
bdn0              10.8.1.2  00:02:38  00:01:37       1
brf0              10.9.1.2  00:02:38  00:01:37       1
~~~

And be sure to read through the [user manual](http://docs.frrouting.org/en/latest/).
