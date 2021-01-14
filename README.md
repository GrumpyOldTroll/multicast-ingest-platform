# Intro

This is a guide for setting up an ingest platform to pull in multicast
traffic originating outside your local network.

At this stage only IPv4 is supported.  Once IPv6 is supported in
[FRR](https://frrouting.org/)'s [PIM](https://tools.ietf.org/html/rfc7761) implementation, we hope to upgrade this project to support
IPv6 as well.

This is a [DRIAD](https://tools.ietf.org/html/rfc8777)-based proof of concept that responds to [SSM](https://tools.ietf.org/html/rfc4607) joins to externally-supplied (S,G)s by ingesting multicast traffic from outside the local network.  It works by discovering an AMT relay that's specific to the source of the (S,G).  It uses no explicit source-specific configuration, and has no explicit peering with the source's network.

This concept was first presented at the mboned meeting at IETF 103:

 * [Video](https://www.youtube.com/watch?v=bCy7j-DoGGc&t=56m38s)
 * [Slides](https://datatracker.ietf.org/meeting/103/materials/slides-103-mboned-draft-jholland-mboned-driad-amt-discovery-00)

The idea is to make it so if someone on the internet is providing multicast
reachable via an AMT relay, you can receive it as multicast within your
network by setting up an ingest device according to these instructions.

You'll need to get your network to propagate source-specific PIM Join
messages to this device for joins to (S,G)s from outside your network.  But
as long as you can do that, you shouldn't need anything special configured
for multicast from different sources--anyone who sets up the right
AMTRELAY DNS record in the DNS reverse IP tree for their source's IP
should be able to provide traffic to your network's clients.

(NB: if you're using the [sample-network setup](sample-network), there is unfortunately a
[route added](sample-network/border-rtr/etc/frr/staticd.conf#L12) for our known source IPs at present.
This is a workaround because FRR's MRIB does not yet work right.  We hope to
also remove this hacked static route when we can get FRR's rpf fixed.  This
source-specific configuration should not be required for a Cisco- or Juniper-
based network, because configuring a default route for the multicast
routing table toward the ingest point works on those platforms.)

# Setup

## Prerequisites

  - Docker and privileged access.
  - Unicast connectivity to the internet, including DNS.  (Can be via the same downstream multicast network or a different interface.)
  - Downstream multicast-capable network running PIM, with an RPF to this device for the sources you want to ingest (e.g. with "ip mroute 0.0.0.0/0 \<interface\>" towards this device's interface)

## Installation

There's 3 different kinds of docker containers that will be running:
 - the [master ingest router](https://hub.docker.com/r/grumpyoldtroll/ingest-rtr).  Directly connected to the multicast network and running PIM.
 - a [dummy upstream router](https://hub.docker.com/r/grumpyoldtroll/pim-dummy-upstream).  (This is currently necessary as a workaround for another FRR bug, but again hopefully should be possible to remove one day.)
 - Potentially multiple [AMT gateway](https://hub.docker.com/r/grumpyoldtroll/amtgw) containers that get launched by the ingest router

You'll install the first 2 containers, and the ingest-rtr will launch other
docker containers autonomously in response to PIM messages, in order to
ingest traffic over AMT and feed it as native multicast into your network.

There's 3 docker network pieces to this setup:
 - **mcast-out**: the connection to the external multicast network.  (This name MAY be changed if you like, but MUST be alphabetically earlier than mcast-xmit due to a [docker issue](https://github.com/moby/moby/issues/25181).)
 - **amt-bridge**: the internal network that AMT gateways use to open the tunnels they establish to the outside.  This name MUST be "amt-bridge", it is directly used from inside the ingest-rtr.
 - **mcast-xmit**: the internal network where multicast comes out from the AMT gateways and gets forwarded to mcast-out.  This name MUST be "mcast-xmit", it is directly used from inside the master.  (If you change the source and thus change this name, it still MUST be alphabetically later than BOTH mcast-out and amt-bridge, due to a [bug in docker](https://github.com/moby/moby/issues/25181))

### Variables

For convenience, the "Commands" section below uses these variables that should be configured based on your network the ingest device is plugging into:

  - **IFACE**:  the physical interface on the host that you'll be plugging into your multicast network.  (I named mine irf for "ingest reflector", but it should match the name of the physical interface on your host machine.)
  - **GATEWAY**: the IP address of the gateway for the ingest device's connection within your multicast network.  This should be the next hop toward a default route out that interface.
  - **SUBNET**: the subnet for PIMD and GATEWAY
  - **PIMD**: the IP address the PIM adjacency will use for connecting over IFACE, from inside the container.  If you are using IFACE for other traffic, this IP has to be different from the IP address for the host.  (There's a sample command below that tries to extract it from the output of "ip addr show dev $IFACE" and then add one.)

~~~bash
IFACE=irf0
GATEWAY=10.9.1.1
SUBNET=10.9.1.0/24
PIMD=10.9.1.3
#pimbase=$(ip addr show dev ${IFACE} | grep "inet " | tail -n 1 | awk '{print $2;}' | cut -f1 -d/)
#PIMD=$(python3 -c "from ipaddress import ip_address as ip; x=ip('${pimbase}'); print(ip(x.packed[:-1]+((x.packed[-1]+1)%256).to_bytes(1,'big')))")


# you MAY change these, but shouldn't need to.  This is the internal
# network where the native multicast arrives unwrapped from AMT, and
# these addresses never appear outside a virtual bridge internal to this
# host.
INTERNALNET=10.11.1.0/24
INTERNALUPSTREAM=10.11.1.2

# create the networks:
sudo docker network create --driver bridge amt-bridge

sudo docker network create --driver macvlan \
    --subnet=${SUBNET} --gateway=${GATEWAY} \
    --opt parent=${IFACE} mcast-out

sudo docker network create --driver bridge \
    --subnet=${INTERNALNET} mcast-xmit

# create the upstream dummy neighbor
sudo docker run --name upstream-dummy-nbr \
    -d --restart=unless-stopped \
    --log-opt max-size=2m --log-opt max-file=5 \
    --privileged --network mcast-xmit \
    --ip ${INTERNALUPSTREAM} grumpyoldtroll/pim-dummy-upstream:latest

# to improve performance of the first join, pull the amtgw image:
sudo docker pull grumpyoldtroll/amtgw:latest

# create the master ingest router.  NB: This needs the docker socket
# attached so it can launch new docker containers.
sudo docker create --name ingest-rtr \
    --restart=unless-stopped --privileged \
    --network mcast-out --ip ${PIMD} \
    --log-opt max-size=2m --log-opt max-file=5 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    grumpyoldtroll/ingest-rtr:latest ${INTERNALUPSTREAM}
sudo docker network connect mcast-xmit ingest-rtr
sudo docker start ingest-rtr
~~~

### NATting AMT Traffic

Assuming you have a default route on your host and that's the way
you want your AMT traffic to flow, you don't need to do this section.

However, if you have a default route that's a management IP, and you
want the AMT traffic to route out through the multicast network, you
can configure the routing for traffic from the amt-bridge to point
your traffic into the multicast-capable network instead.

Doing this requires that the multicast network can route traffic to
the internet with unicast from the host's IP (PIMD) on that link.

You can do this with source routing through a separate table:

~~~bash
# put the subnet of amt-bridge in AMTSRCNET:
AMTSRCNET=$(sudo docker network inspect amt-bridge | grep Subnet | sed -e 's/ *"Subnet": "\(.*\)",/\1/')

# find the ifname of the amt-bridge gateway.  Without the route that
# uses this, ARP fails unfortunately.  (On ubuntu 20+ you can use
# "iproute udp dport 2268" on the rule for the source traffic instead
# of the extra route in table 10, but on the ubuntu 18.04 I'm currently
# using those features are unsupported)
AMTGWIP=$(sudo docker network inspect amt-bridge | grep Gateway | sed -e 's/ *"Gateway": "\(.*\)",*/\1/')
AMTGWIF=$(ip addr show | grep ${AMTGWIP} | awk '{print $7;}')

# add a routing table for the data network:
sudo ip route add table 10 to ${SUBNET} dev ${IFACE}
sudo ip route add table 10 to ${AMTSRCNET} dev ${AMTGWIF}
sudo ip route add table 10 to default via ${GATEWAY} dev ${IFACE}

# send traffic from the AMT bridge into that routing table and nat it:
sudo ip rule add from ${AMTSRCNET} table 10 priority 50
~~~

# Troubleshooting

## What's going on

The proof of concept itself is just [pimwatch.py](src/pimwatch.py), which runs:

 * [tcpdump](https://manpages.debian.org/stretch/tcpdump/tcpdump.8.en.html) to watch [PIM](https://tools.ietf.org/html/rfc7761) packets.
 * [dig](https://manpages.debian.org/stretch/dnsutils/dig.1.en.html) for DRIAD's [DNS querying](https://tools.ietf.org/html/rfc8777#section-2.2)
 * an [amtgw](https://hub.docker.com/r/grumpyoldtroll/amtgw) docker container to establish tunnels, and
 * an "ip igmp join" command in frr to send a join/leave through the tunnel.

The rest of the setup is so that there are PIM packets for pimwatch.py to watch and respond to.

## Checking the basics

You might want to make sure there's not some external kind of block happening.  For this, I generally try receiving a trickle stream I leave running for this purpose on 23.212.185.4->232.1.1.1:

~~~
# after git clone https://github.com/GrumpyOldTroll/libmcrx to get libmcrx/driad.py
SOURCEIP=23.212.185.4
GROUPIP=232.1.1.1
DISCIP=$(python3 libmcrx/driad.py $SOURCEIP)
sudo docker run -d --rm --name amtgw --privileged grumpyoldtroll/amtgw:latest $DISCIP
sudo docker run -it --rm --name rx2 grumpyoldtroll/iperf-ssm:latest --server --udp --bind $GROUPIP --source $SOURCEIP --interval 1 --len 1500 --interface eth0
~~~

If that starts giving you one line per second that looks something like this, it means the AMT connectivity is working and there's an active sender:

~~~
$ sudo docker run -it --rm --name rx2 grumpyoldtroll/iperf-ssm:latest --server --udp --bind $GROUPIP --source $SOURCEIP --interval 1 --len 1500 --interface eth0
setting perf ip4 ttl to 1
------------------------------------------------------------
Server listening on UDP port 5001
Binding to local address 232.1.1.1
Joining multicast group  232.1.1.1
Joining multicast group on interface  eth0
Accepting multicast group source  23.212.185.4
Receiving 1500 byte datagrams
UDP buffer size:  208 KByte (default)
------------------------------------------------------------
setting perf ip4 ttl to 1
[  3] local 232.1.1.1 port 5001 connected with 23.212.185.4 port 5001
[ ID] Interval       Transfer     Bandwidth        Jitter   Lost/Total Datagrams
[  3]  0.0- 1.0 sec   125 Bytes  1.00 Kbits/sec   0.000 ms   87/   88 (99%)
[  3]  1.0- 2.0 sec  0.00 Bytes  0.00 bits/sec   0.000 ms    0/    0 (-nan%)
[  3]  2.0- 3.0 sec   250 Bytes  2.00 Kbits/sec   0.397 ms    0/    2 (0%)
^CWaiting for server threads to complete. Interrupt again to force quit.
[  3]  3.0- 4.0 sec   125 Bytes  1.00 Kbits/sec   0.377 ms    0/    1 (0%)
~~~

The first line reporting a high loss is an artifact of the way iperf is running.  In this model, the sender (or "client", as iperf calls it, which is kind of weird but makes some twisted sense for UDP, since servers are the ones who listen) is running from my source all the time, and the receiver (or "server" as iperf calls it) starts listening at some arbitrary time, so it sees a bunch of "loss".  The sender is restarted every 15 minutes and sends a single 125-byte packet per second (1kbps), each of which counts toward the receiver's stats.

If you don't see the lines below "[  3] local 232.1.1.1 port 5001 connected with 23.212.185.4 port 5001", or they aren't updating approximately once per second, it can mean the sender is not up right now, or that something else basic that the ingest relies on isn't working yet.
Usually (but not always) you can tell by looking at the AMT traffic on UDP port 2268.  If you see 2-way traffic between your host and $DISCIP, the tunnel is probably connected, otherwise probably not.

## Where to look

I usually do the first few stages of troubleshooting with tcpdump, since it gives you a good idea of where the problem lies.

TBD: add some sample pcaps with network diagram locations.

## How to get in once you've found where it's broken

Access to the containers underlying file system with bash:

~~~bash
sudo docker exec -it ingest-rtr bash
~~~

There are logs in /var/log/frr/, and frr config files in /etc/frr/.

Access to the router configuration with vtysh:

~~~bash
sudo docker exec -it ingest-rtr vtysh
~~~

This is similar to using a Cisco command line, and supports many
useful commands like "show ip route", "show ip pim neighbor", 
"show ip pim state", "show running", etc.  There's a great manual
and typing a ? will show commands that can come next.

It's also often helpful to see what's happening in the ingest-rtr, there's
logging that at least shows whether joins are reaching the router and
what gateways are launched (also visible with "docker container ls"):

~~~bash
sudo docker logs -f ingest-rtr
~~~

# Resources

I maintain a few live streams.  These may not remain up forever, so if they seem down, contact me and I can possibly launch them again or point you to an updated location.

 * with [iperf-ssm](https://github.com/GrumpyOldTroll/iperf-ssm) (1kbps): iperf --server --udp --bind 232.1.1.1 --source 23.212.185.5 --interval 1 --len 1500 --interface en5
 * with [vlc](https://www.videolan.org/index.html) (about 5mbps, streaming [blender project](https://www.blender.org/about/projects/) videos): vlc udp://23.212.185.5@232.10.10.2:12000

Akamai also has some proprietary receivers and corresponding source streams that are under development.  [Contact me](mailto:jholland@akamai.com) if you would like to arrange to do some experiments or trials.

## Internet2

There are also a number of video streams active on [internet2](https://www.internet2.edu/) and reachable by some AMT relays.

 * Lauren Delwiche wrote and maintains a [menu of content](https://multicastmenu.herokuapp.com/) app
 * William Zhang has published a [scanning script](https://github.com/willzhang05/senior-research/blob/master/find_src_i2.py) to find live multicast streams by scraping the [Routing Table Proxy](https://routerproxy.wash2.net.internet2.edu/routerproxy/) published by [Indiana University](https://routerproxy.wash2.net.internet2.edu/).
 * Lenny Giuliano maintains a "[MTTG](https://www.ietf.org/proceedings/104/slides/slides-104-mboned-mttg-01)" (Multicast to the Grandma) slack server where you can learn about all this and more.  If you'll be working in this space and you want to get in touch with the people driving this technology, contact me (open an issue if you like) and I can get you an invite.

### AMT in VLC

It should also be noted that VLC at version 4.02 and later contains an embedded AMT Gateway that can form a unicast tunnel to an AMT relay to directly ingest multicast traffic from an external network.  The urls beginning with "amt://" in the multicastmenu.herokuapp.com menu will ask VLC to connect this way, whereas "udp://" with the same addresses will only use native multicast.

If as an end user you just want to view the content and you don't care about packet replication in the local network, it is possible to do so with just a recent VLC client, thanks to Natalie Landsberg and the work she did adding the embedded AMT Gateway capability to VLC, by using "amt://source@group:port".

However, If you want to have in-network packet replication to gain the bandwidth benefits of multicast, this is not recommended because it will open a unicast tunnel from the app to the relay in Internet2, bypassing the use of multicast.

If, as a network operator, you have many users doing this when you're providing native multicast reachability for traffic from those sources, it may become necessary to block port 2268 for your users or require them to use a VPN if they need to do this, if the practice of using amt: instead of udp: from within VLC becomes widespread.  However, at the time of this writing (late 2020) it's usually only a few people experimenting with multicast that do this, and can generally be ignored.

### DNS Hacks to Ingest Traffic from Internet2

Most of the content on Internet2 has not yet published resource records
for [DRIAD](https://tools.ietf.org/html/rfc8777) to support dynamic AMT
discovery at the time of this writing.

However, for local experimentation it's possible to inject records into
your own DNS server.  Thanks to Lenny Giuliano's leadership and Juniper's
support, several public AMT relays are operational on Internet2, and can
export content published to Internet2 with multicast.

The [sample-network](sample-network) bind configuration contains [some](sample-network/border-rtr/etc/bind/zones/reverse.51.131.174.129.in-addr.arpa.zone#L15) [example](sample-network/border-rtr/etc/bind/zones/reverse.40.93.128.131.in-addr.arpa.zone#L14) [zones](sample-network/border-rtr/etc/bind/zones/reverse.201.138.250.162.in-addr.arpa.zone#L20) that map traffic from some of those source IPs on Internet2 (active at the time of this writing) to the amt-relay.m2icast.net domain name that the public AMT relays on Internet2 are using.

Doing this enables ingest of that content via this ingest platform if those DNS records are seen by the ingest platform.  (Note that using these zones is a local hijack of the reverse-IP DNS records for those sources, and may locally suppress other records such as PTR lookups that are published to the global DNS by the actual controllers of those zones, and may not be suitable for some environments.)

