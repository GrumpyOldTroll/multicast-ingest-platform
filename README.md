# Intro

This is a guide for setting up an ingest platform to pull in multicast
traffic originating outside your local network.

At this stage only IPv4 is supported.  Once IPv6 is supported in
[FRR](https://frrouting.org/)'s PIM implementation, we hope to upgrade this project to support
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
 - *mcast-out*: the connection to the external multicast network.  (This name MAY be changed if you like.)
 - *amt-bridge*: the internal network that AMT gateways use to open the tunnels they establish to the outside.  This name MUST be "amt-bridge", it is directly used from inside the ingest-rtr.
 - *mcast-xmit*: the internal network where multicast comes out from the AMT gateways and gets forwarded to mcast-out.  This name MUST be "mcast-xmit", it is directly used from inside the master.  (If you change the source and thus change this name, it still MUST be alphabetically later than BOTH mcast-out and amt-bridge, due to a bug in docker: https://github.com/moby/moby/issues/25181)

### Variables

For convenience, the "Commands" section below uses these variables that should be configured based on your network the ingest device is plugging into:

  - *IFACE*:  the physical interface on the host that you'll be plugging into your multicast network.  (I named mine irf for "ingest reflector", but it should match the name of the physical interface on your host machine.)
  - *PIMD*: the IP address for this ingest device within your multicast network. You may set it to match your interface's IP, or you can set it to a specific other IP value appropriate to your network. (The command below tries to extract it from the output of "ip addr show dev $IFACE)
  - *GATEWAY*: the IP address of the gateway for the ingest device's connection within your multicast network.  This should be the next hop toward a default route out that interface.
  - *SUBNET*: the subnet for PIMD and GATEWAY

~~~
IFACE=irf0
PIMD=$(ip addr show dev ${IFACE} | grep "inet " | awk '{print $2;}' | cut -f1 -d/)
GATEWAY=10.9.1.1
SUBNET=10.9.1.0/24

# you MAY change these, but shouldn't need to.  This is the internal
# network where the native multicast arrives unwrapped from AMT, and
# these addresses never appear outside a virtual bridge internal to this
# host.
INTERNALNET=10.11.1.0/24
INTERNALUPSTREAM=10.11.1.2

# create the networks:
sudo docker network create --driver bridge amt-bridge

sudo docker network create --driver macvlan --subnet=${SUBNET} --gateway=${GATEWAY} --opt parent=${IFACE} mcast-out

sudo docker network create --driver bridge --subnet=${INTERNALNET} mcast-xmit

# create the upstream dummy neighbor
sudo docker run -d --name upstream-dummy-nbr --restart=unless-stopped --privileged --network mcast-xmit --ip ${INTERNALUPSTREAM} grumpyoldtroll/pim-dummy-upstream:latest

# create the master ingest router.  NB: This needs the docker socket
# attached so it can launch new docker containers.
sudo docker create --name ingest-rtr --restart=unless-stopped --privileged --network mcast-out --ip ${PIMD} -v /var/run/docker.sock:/var/run/docker.sock grumpyoldtroll/ingest-rtr:latest ${INTERNALUPSTREAM}
sudo docker network connect mcast-xmit ingest-rtr
sudo docker start ingest-rtr

# to improve performance of the first join, pull the amtgw image:
sudo docker pull grumpyoldtroll/amtgw:latest
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

~~~
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

Access to the containers underlying file system with bash:

~~~
sudo docker exec -it ingest-rtr bash
~~~

There are logs in /var/log/frr/, and frr config files in /etc/frr/.

Access to the router configuration with vtysh:

~~~
sudo docker exec -it ingest-rtr vtysh
~~~

This is similar to using a Cisco command line, and supports many
useful commands like "show ip route", "show ip pim neighbor", 
"show ip pim state", "show running", etc.  There's a great manual
and typing a ? will show commands that can come next.

It's also often helpful to see what's happening in the ingest-rtr, there's
logging that at least shows whether joins are reaching the router and
what gateways are launched (also visible with "docker container ls"):

~~~
sudo docker logs -f ingest-rtr
~~~

## What's going on

The proof of concept itself is just [pimwatch.py](src/pimwatch.py), which runs:

 * [tcpdump](https://manpages.debian.org/stretch/tcpdump/tcpdump.8.en.html) to watch [PIM](https://tools.ietf.org/html/rfc7761) packets.
 * [dig](https://manpages.debian.org/stretch/dnsutils/dig.1.en.html) for DRIAD's [DNS querying](https://tools.ietf.org/html/rfc8777#section-2.2)
 * an [amtgw](https://hub.docker.com/r/grumpyoldtroll/amtgw) docker container to establish tunnels, and
 * an "ip igmp join" command in frr to send a join/leave through the tunnel.

The rest of the setup is so that there are PIM packets for pimwatch.py to watch and respond to.

