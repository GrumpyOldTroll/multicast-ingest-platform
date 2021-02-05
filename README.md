# Multicast Ingest Overview

This is a guide for setting up an ingest platform to pull in multicast
traffic originating outside your local network.

At this stage only IPv4 is supported.  Once IPv6 is supported in
[FRR](https://frrouting.org/)'s and/or an [open-source pimd](https://github.com/troglobit/pimd) implementation of [PIM](https://tools.ietf.org/html/rfc7761), we hope to upgrade this project to support IPv6 as well.

This is a [DRIAD](https://tools.ietf.org/html/rfc8777)-based proof of concept that responds to [SSM](https://tools.ietf.org/html/rfc4607) joins to externally-supplied (S,G)s by ingesting multicast traffic from outside the local network.  It works by discovering an AMT relay that's specific to the source of the (S,G).  It uses no explicit source-specific configuration, and has no explicit peering with the source's network.

This concept was first presented at the mboned meeting at IETF 103:

 * [Video](https://www.youtube.com/watch?v=bCy7j-DoGGc&t=56m38s)
 * [Slides](https://datatracker.ietf.org/meeting/103/materials/slides-103-mboned-draft-jholland-mboned-driad-amt-discovery-00)

The idea is to make it so if someone on the internet is providing multicast reachable via an AMT relay, you can receive it as multicast within your network by setting up an ingest device according to these instructions, as long as the sender has set up the appropriate metadata and DNS records to support discovery.

You'll need to get your network to propagate source-specific PIM Join messages to this device for joins to (S,G)s from outside your network.
But as long as you can do that, you shouldn't need anything special configured in order to support multicast from different sources--anyone who sets up the right AMTRELAY DNS record in the DNS reverse IP tree for their source's IP should be able to provide traffic to your network's clients.

(NB: if you're using the [sample-network setup](sample-network), there is unfortunately a [route added](sample-network/border-rtr/etc/frr/staticd.conf#L12) for our known source IPs at present.
This is a workaround because FRR's MRIB does not yet work right.  We hope to
also remove this hacked static route when we can get FRR's rpf fixed.
This source-specific configuration should not be required for a Cisco- or Juniper- based network, because configuring a default route for the multicast routing table toward the ingest point works on those platforms.)

# Design

You can skip this section if you just want to make it run, but this is a brief overview of what will end up running on the ingest platform device and what its behavior is.

## Overview

The goal is to send externally generated multicast traffic by making a tunnel to an auto-discovered [AMT](https://tools.ietf.org/html/rfc7450) relay for traffic joined by subscribers within your network.

There are a several components the platform uses to achieve this goal, detailed below.  Here's the overall diagram:

![ingest-platform](ingest-platform-diagram.png)

## Docker Containers

 - multiple `amtgw` gateway containers (one per actively subscribed source IP).\
   Each of these runs an AMT gateway instance, which forms a unicast tunnel with the AMT relay associated with the source IP
 - one `driad-ingest` container.\
   This uses [DRIAD](https://tools.ietf.org/html/rfc8777) to discover the appropriate AMT relay given the source IP (from the (S,G)), launches the AMT gateway containers as needed, and maintains an IGMP/MLD join locally, which the AMT gateway will use.
 - one `pimwatch` container.\
   This establishes a [PIM](https://tools.ietf.org/html/rfc7761) adjacency with the downstream multicast network and monitors join/prune events from the network to determine the current set of joined (S,G)s (exported via a joinfile).  It also forwards the multicast traffic from the docker network where the amtgw containers are sending it into the downstream network (this isolates the internal IGMP/MLD membership reports sent to the AMT gateways, so they aren't exposed to the multicast network).\
   The [current implementation](https://github.com/troglobit/pimd) in the `pimwatch` container requires an upstream PIM neighbor in order to operate (though ordinarily a PIM router would be able to forward traffic from a directly connected sender even without an upstream PIM adjacency).  As a workaround for this implementation problem, there is a `pim-dummy-upstream` container whose only purpose is to enable the operation of the `pimwatch` container.  (We aspire to remove the dummy-upstream in a future version.)
 - optionally, one `cbacc` container.\
   This uses [CBACC](https://datatracker.ietf.org/doc/draft-ietf-mboned-cbacc/) metadata to limit the traffic permitted.  If the users within your network subscribe to more than the permitted total bandwidth of traffic, this will prevent the ingest platform from subscribing to traffic that exceeds the limit (so subscribers to some flows will not receive traffic).

These containers are connected by some docker networks for routing traffic, plus some "joinfiles" to communicate the set of currently subscribed (S,G)s between containers.

## Docker Networks

The networks:

 - `amt-bridge`: a [docker bridge network](https://docs.docker.com/network/bridge/) with [NAT](https://en.wikipedia.org/wiki/Network_address_translation) to the internet for unicast traffic.\
   This will carry 2-way traffic to the internet for:

   - AMT (UDP port 2268) for the AMT tunnels from the `amtgw` containers to the discovered relays
   - DNS (UDP port 53) for [AMTRELAY](https://tools.ietf.org/html/rfc8777#section-4) record queries from the `driad-ingest` container, and [SRV](https://tools.ietf.org/html/rfc2782), [A](https://en.wikipedia.org/wiki/List_of_DNS_record_types#Resource_records), and [AAAA](https://en.wikipedia.org/wiki/IPv6_address#Domain_Name_System) record queries from the `cbacc` container
   - HTTPS (TCP port 443) for the discovered [DORMS](https://datatracker.ietf.org/doc/draft-ietf-mboned-dorms/) server carrying the [CBACC](https://datatracker.ietf.org/doc/draft-ietf-mboned-cbacc/) metadata (which includes the (S,G)'s bitrate).

 - `native-mcast-ingest`: a local bridge where the native multicast traffic lands.\
   The traffic on this network is:

   - native multicast traffic from the `amtgw` containers.  These are the data packets that users in the network have subscribed to receive.
   - IGMP/MLD membership queries from the `amtgw` containers and membership reports from the `driad-ingest` container.
   - PIM hello packets between the `pimwatch` container and the `pim-upstream-dummy`

 - `downstream-mcast`: a [macvlan](https://docs.docker.com/network/macvlan/) network connecting the `pimwatch` container to the downstream multicast-enabled network.\
   This network's parent interface should be the physical interface connecting to the multicast-enabled network.  It carries:

   - the PIM messages of the connected multicast-capable network
   - the native multicast traffic to be forwarded through the network.
   - If this interface is also the default route to the internet for the host, the other traffic on the box could also end up passing through this network (for instance, the NATted packets from the amt-bridge network, or ssh sessions to the host machine).

### Docker Network Constraints

NB: If you try to change the names of these networks, please be aware of a surprising [docker issue](https://github.com/moby/moby/issues/25181) that places constraints on the lexical ordering of the names.

 - `amt-bridge` MUST be lexically earlier than `native-mcast-ingest`, otherwise the interface names visible inside the `amtgw` containers will not be the expected eth0 for the unicast AMT connection and eth1 for producing the native multicast, but would instead be reversed.
    - You would see this problem for example if you renamed "amt-bridge" to "outside-bridge", because 'o' from "outside" is lexically later than 'n' from "native", as opposed to 'a' which is earlier.
 - `downstream-mcast` MUST be lexically earlier than `native-mcast-ingest`, otherwise the interface names visible inside the `pimwatch` container will not be the expected eth0 for downstream and eth1 for upstream, but would instead be reversed.

## Joinfiles

The `pimwatch` and `cbacc` containers produce joinfiles, and the `docker-mgr` and `cbacc` containers consume joinfiles.

Consuming a joinfile is done with the [watchdog](https://pypi.org/project/watchdog/) python library (where available, such as on a modern linux kernel, it uses a platform-specific notification scheme such as [inotify](https://man7.org/linux/man-pages/man7/inotify.7.html) to alert watchers on changes to the file).

The joinfiles contain a comma-separated source ip, group ip per line.

~~~
23.212.185.5,232.1.1.1
23.212.185.4,232.10.10.2
~~~

The (S,G) entries on each line indicate the joined (S,G)s for which traffic should be ingested if possible.

`pimwatch` will change the file it produces whenever a join/prune message is observed on the physical interface.

When the pimwatch joinfile changes, `cbacc` will respond by possibly changing the file it produces, depending on the results of comparing the expected aggregate bitrate to its bandwidth limit.

When the cbacc joinfile changes, driad-ingest will respond by launching or shutting down amtgw instances if the active source list changes, and by starting a process that maintains a joined state for each (S,G), so that the AMT gateway instances will ingest traffic from the relays they connect to.

In the case of the joinfile that CBACC consumes, it also may contain (optionally) a third comma-separated value for "population", meaning the number of subscribed users.  This will influence the filtering of (S,G)s to favor the flows producing the highest offload (calculated as "(population-1)\*bitrate").  Where offload is equal (typically at 0, due to a population of 1 which is the assumed value when no population is given), it instead favors smaller flows.

It is possible to edit joinfiles by other means than these, to be consumed by the containers that consume them.  They're just files on the file system.  These containers will regularly overwrite the joinfiles they produce, so things like manual edits will not be stable when pimwatch or cbacc is actively driving a joinfile (though they might sometimes be useful for troubleshooting or experimenting).

# Setup

## Prerequisites

  - Docker and privileged access on the ingest device.
  - Outbound UDP and TCP unicast connectivity to the internet that permits return traffic for the same connection.  (This can be via the same downstream multicast network or a different interface, and can have layers of external NAT or not, provided that return traffic for outbound connections that were opened is permitted both for UDP and TCP.)
  - Downstream multicast-capable network running PIM, with an RPF to the ingest device for the sources you want to ingest (e.g. with "ip mroute 0.0.0.0/0 \<interface\>" towards this device's interface from an adjacent PIM router on an end user's default route)
  - Receivers downstream of the multicast-capable network with multicast receiving applications that use source-specific multicast joins to subscribe to multicast traffic (e.g. [vlc](https://www.videolan.org/vlc/) or [iperf-ssm](https://github.com/GrumpyOldTroll/iperf-ssm) or some sample apps we can provide on request.)

NB: The containers have been tested with ubuntu 20.04 in a default server installation (plus `apt-get install -y docker.io`).
In some other setups, we have seen firewall or apparmor rules that interfere with the expected behavior of some of the containers.
In at least one case, a default CentOS 8 installation was overwritten with ubuntu 20.04 rather than trying to troubleshoot it, and we're still not sure what all the issues were yet.

NB2: On ubuntu 18 and 20, the default "sudo apt-get install docker.io" state has 2 known issues:

  - docker containers don't restart after startup by default.  According to [online sources](https://docs.docker.com/engine/install/linux-postinstall/#configure-docker-to-start-on-boot) it's possible to fix this by manually running this after installing:

    ~~~
    sudo systemctl enable docker.service
    sudo systemctl enable container.service
    ~~~

  - all docker commands require sudo after the default install.  Note that although this is [simple to fix](https://docs.docker.com/engine/install/linux-postinstall/#manage-docker-as-a-non-root-user), some containers require --privileged, and these may need to be run with sudo regardless.  Hopefully a future version can improve on this by using more [narrow capabilities](https://docs.docker.com/engine/reference/run/#runtime-privilege-and-linux-capabilities) explicitly.
    - the setup commands below currently assume that you are running docker commands with sudo privileges for all docker commands.

## Common Variables

The commands below use these environment variables, collected here for easier tuning according to your setup.

These settings can be pasted verbatim if using the [sample-network](sample-network) setup, but in other cases it will be necessary to change values to match your environment.

~~~
IFACE=irf0
SUBNET=10.9.1.0/24
PIMD=10.9.1.2
# these may be helpful for extracting the IP of $IFACE in a script:
#pimbase=$(ip addr show dev ${IFACE} | grep "inet " | tail -n 1 | awk '{print $2;}' | cut -f1 -d/)
#PIMD=$(python3 -c "from ipaddress import ip_address as ip; x=ip('${pimbase}'); print(ip(x.packed[:-1]+((x.packed[-1]+1)%256).to_bytes(1,'big')))")

# MiBps limit (of UDP payload bit rates)
BW_MAX_MIBPS=50

JOINFILE=${HOME}/pimwatch/pimwatch.sgs
CBJOINFILE=${HOME}/cbacc/cbacc.sgs

INGEST_VERSION=0.0.5
~~~

Variable meanings:

  - **IFACE**:  the physical interface on the host that you'll be plugging into your multicast network.  (I named mine irf for "ingest reflector", but it should match the name of the physical interface on your host machine.)
  - **SUBNET**: the subnet for PIMD
  - **PIMD**: the IP address the PIM adjacency will use for connecting over IFACE, from inside the container.  If you are using IFACE for other traffic, this IP has to be different from the IP address for the host.  (There's a sample command below that tries to extract it from the output of "ip addr show dev $IFACE" and then add one.)
  - **BW_MAX_MIBPS**: The max bandwidth, to be enforced by `cbacc` according to the flow metadata.
  - **JOINFILE**: The full path of the joinfile produced by `pimwatch` (consumed by `cbacc` or `driad-ingest` if running without cbacc)
  - **CBJOINFILE**: The full path of the joinfile consumed by `driad-ingest` (produced by `cbacc` or `pimwatch` if running without cbacc)

Because several of the containers require privileged access (`pimwatch`, `pim-upstream-dummy`, and `amtgw` for access to the kernel's multicast routing table, plus creation of a tap interface for `amtgw` and packet capture and sending of PIM packets for `pimwatch` and `pim-upstream-dummy`, and `driad-ingest` for access to the docker socket so it can launch amtgw instances with privileged access).

## Network Setup

~~~
sudo docker network create --driver bridge amt-bridge
sudo docker network create --driver bridge mcast-native-ingest
sudo docker network create --driver macvlan \
    --subnet=${SUBNET} \
    --opt parent=${IFACE} downstream-mcast

# to improve performance of the first join, pull the amtgw image:
sudo docker pull grumpyoldtroll/amtgw:0.0.4
~~~

## Running Containers

### pimwatch

The pimwatch container runs an instance of [PIM](https://tools.ietf.org/html/rfc7761) on the downstream interface and responds to join and prune messages by updating a joinfile and by forwarding matching traffic that arrives for joined (S,G)s at the upstream interface on the downstream interface.

~~~
# run the upstream dummy neighbor
sudo docker run \
    --name upstream-dummy-nbr \
    --privileged \
    --network mcast-native-ingest \
    --log-opt max-size=2m --log-opt max-file=5 \
    -d --restart=unless-stopped \
    grumpyoldtroll/pim-dummy-upstream:0.0.4

# ensure the joinfile is present
mkdir -p $(dirname ${JOINFILE}) && touch ${JOINFILE}

# create pimwatch, attach extra network, and start it
sudo docker create \
    --name pimwatch \
    --privileged \
    --network downstream-mcast --ip ${PIMD} \
    --log-opt max-size=2m --log-opt max-file=5 \
    --restart=unless-stopped \
    -v $(dirname ${JOINFILE}):/etc/pimwatch/ \
    grumpyoldtroll/pimwatch:${INGEST_VERSION} \
      -v \
      --joinfile /etc/pimwatch/$(basename ${JOINFILE}) && \
sudo docker network connect mcast-native-ingest pimwatch && \
sudo docker start pimwatch
~~~

### cbacc

The cbacc container uses bandwidth metadata according to the [CBACC](https://datatracker.ietf.org/doc/draft-ietf-mboned-cbacc/) spec to ensure that the bandwidth of ingested traffic does not exceed the limit (in MiBps) given to the "bandwidth" parameter.

If you want to permit ingesting traffic without cbacc metadata, you can provide a `--default <bw>` value to this call, and it should treat flows without available metadata as having the given value in MiBps.

If you don't want to run cbacc at all, you don't have to.  Set `CBJOINFILE=$JOINFILE` before starting driad-ingest and don't launch cbacc, and driad-ingest will use the joinfile produced by pimwatch, rather than the filtered joinfile produced by cbacc.

NB: the default behavior of cbacc when no CBACC metadata is present for an (S,G) is to set its bitrate above the maximum bitrate, so it will always be blocked.  If you want to avoid ingesting traffic from sources that do not have CBACC metadata, remove the `--default <bandwidth>` override of the "effective MiBps" estimate for unknown (S,G)s, which will cause cbacc to avoid allowing them.  (And if the external flows without cbacc will exceed 12mbps, adjust the parameter accordingly.)

~~~
# ensure both joinfiles are present
mkdir -p $(dirname ${JOINFILE}) && touch ${JOINFILE}
mkdir -p $(dirname ${CBJOINFILE}) && touch ${CBJOINFILE}

# run cbacc
sudo docker run \
    --name cbacc \
    --log-opt max-size=2m --log-opt max-file=5 \
    --network amt-bridge \
    -v $(dirname ${JOINFILE}):/var/run/cbacc-in/ \
    -v $(dirname ${CBJOINFILE}):/var/run/cbacc-out/ \
    --restart=unless-stopped -d \
    grumpyoldtroll/cbacc:${INGEST_VERSION} \
      -v \
      --input-file /var/run/cbacc-in/$(basename ${JOINFILE}) \
      --output-file /var/run/cbacc-out/$(basename ${CBJOINFILE}) \
      --bandwidth ${BW_MAX_MIBPS} \
      --default 12
~~~

### driad-ingest

`driag-mgr` discovers AMT relays suitable for the source IP in an (S,G) of an SSM join, using and AMTRELAY DNS query, roughly as described in [RFC 8777](https://tools.ietf.org/html/rfc8777).

If it's able to discover a suitable AMT relay, it launches an AMT gateway to connect to that relay, and issues joins for (S,G)s with that source IP.

~~~
sudo docker run \
    --name driad-ingest \
    --privileged --network mcast-native-ingest \
    --log-opt max-size=2m --log-opt max-file=5 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v $(dirname $CBJOINFILE):/var/run/ingest/ \
    -d --restart=unless-stopped \
    grumpyoldtroll/driad-ingest:${INGEST_VERSION} \
      --amt amt-bridge \
      --native mcast-native-ingest \
      --joinfile /var/run/ingest/$(basename $CBJOINFILE) -v
~~~

Parameters to the driad-ingest container are:

 * **amt**\
  The docker network that AMT gateways will use for AMT traffic.
 * **native**\
  The docker network that AMT gateways will send native multicast to, after receiving it from an AMT tunnel
 * **joinfile**\
  The location within the container of the joinfile to monitor.

Some things also need to be mounted in the container:

 * **/var/run/docker.sock**\
  The docker socket to use for issuing docker commands to spawn and destroy the AMT gateways
 * **/var/run/ingest/**\
  The directory containing the joinfile that's passed in has to be mounted as a directory.  This is because internally, the file is watched with [inotify](https://man7.org/linux/man-pages/man7/inotify.7.html), which wants to monitor the directory for changes.

# Troubleshooting

There are several things to check.
In this section we'll walk through the output of the [ingest-troubleshoot.sh](ingest-troubleshoot.sh) script run inside a [sample-network](sample-network), with a list of things to look for.

To generate the output, we used the `ingest-troubleshoot.sh` program in this repo, and left it active while subscribing to traffic.

This program launches several ssh sessions running a few diagnostic commands within the network and merges their output into a single text file with timestamps and a tag indicating which session produced each line.

For your network, it's likely that you'll need to edit the ingest-troubleshoot.sh file to use the login for your ingest device as the `INGEST` variable at the bottom if it's different from `user@10.9.1.3`, and likewise may want to change the `ACCESS` variable or remove the calls that use it.

The `watch_container` function will monitor logs produced by the docker containers above, and the other `watch_xxx` functions are running a `tcpdump` that watches for a specific set of traffic.

The output we'll be examining was generated by running 2 commands in separate shells.

~~~
./ingest-troubleshoot.sh | stdbuf -oL -eL tee sample-troubleshoot.log
~~~

To subscribe to traffic from a receiver inside the [sample-network](sample-network/README.md), we ran the `mcrx-check` program from [libmcrx](https://github.com/GrumpyOldTroll/libmcrx):

~~~
$ libmcrx/mcrx-check -s 23.212.185.4 -g 232.1.1.1 -p 5001 -d 0 -c 20
02-03 16:04:34: joined to 23.212.185.4->232.1.1.1:5001 for 2s, 0 pkts received
02-03 16:04:36: joined to 23.212.185.4->232.1.1.1:5001 for 4s, 0 pkts received
02-03 16:04:38: joined to 23.212.185.4->232.1.1.1:5001 for 6s, 0 pkts received
02-03 16:04:40: joined to 23.212.185.4->232.1.1.1:5001 for 8s, 0 pkts received
02-03 16:04:42: joined to 23.212.185.4->232.1.1.1:5001 for 10s, 2 pkts received
02-03 16:04:44: joined to 23.212.185.4->232.1.1.1:5001 for 12s, 4 pkts received
02-03 16:04:46: joined to 23.212.185.4->232.1.1.1:5001 for 14s, 6 pkts received
02-03 16:04:48: joined to 23.212.185.4->232.1.1.1:5001 for 16s, 8 pkts received
02-03 16:04:50: joined to 23.212.185.4->232.1.1.1:5001 for 18s, 10 pkts received
02-03 16:04:52: joined to 23.212.185.4->232.1.1.1:5001 for 20s, 12 pkts received
02-03 16:04:54: joined to 23.212.185.4->232.1.1.1:5001 for 22s, 14 pkts received
02-03 16:04:56: joined to 23.212.185.4->232.1.1.1:5001 for 24s, 16 pkts received
02-03 16:04:58: joined to 23.212.185.4->232.1.1.1:5001 for 26s, 18 pkts received
passed (20/20 packets in 27s)
~~~

That joined the (S,G) with SourceIP=23.212.185.4 and GroupIP=232.1.1.1, and listened on UDP port 5001.
This stream is a 1kbps stream producing 1 packet per second, sourced externally.

## Diagnostics Examination

The full diagnostic output file is in [sample-troubleshoot.log](sample-troubleshoot.log).
In this section we'll point to specific lines that are good indicators to check.
If there's an attempt at a connection that fails, it's very likely that one of these indicator lines is not present, and doing something unexpected.

NB: There are 2 different timestamps at the beginning of many of the lines from tcpdump or the container logs because the first timestamp is from the receiver's clock, where ingest-troubleshoot.sh was launched, and the 2nd timestamp is from the machine where the diagnostic command was running, and in this case they have different time zones configured, and hence are off by 8 hours (PDT vs. GMT).  In some cases, timestamps may further diverge by up to a few seconds when there was a transmission delay in the ssh session.

NB2: In many cases, events that occur at nearly the same time on different machines can easily appear out of order in the log.
This occurs numerous times in this example (for instance, the IGMP message on line 41 must necessarily occur before the PIM message from the access router on line 37, which must necessarily occur before the PIM message from the ingest device on line 31).
This walkthrough covers the events in the order they occur in the network, but when events on different devices are within a short time from one another, they often may appear out of order in the logs.
This is expected behavior, in general.

### IGMPv3 or MLDv2 SSM Join

When a receiver joins an (S,G), the host OS where that receiver is running uses [IGMP](https://www.rfc-editor.org/rfc/rfc3376.html) or [MLD](https://www.rfc-editor.org/rfc/rfc3810.html) to communicate the host's group membership to the network.

At [line 37](sample-troubleshoot.log#L37) of sample-troubleshoot.log we see:

~~~
acc-igmp     16:04:32 00:04:32.026725 IP (tos 0xc0, ttl 1, id 0, offset 0, flags [DF], proto IGMP (2), length 44, options (RA))
acc-igmp     16:04:32     10.7.1.56 > 224.0.0.22: igmp v3 report, 1 group record(s) [gaddr 232.1.1.1 allow { 23.212.185.4 }]
~~~

These lines come from a tcpdump watching the connection between the receiver device and its first-hop router (under the `watch_igmp` function in [ingest-troubleshoot.sh](ingest-troubleshoot.sh#L97):

~~~
tcpdump -i $IFACE -n -vvv igmp
~~~

The key features in these lines are:

 - **acc-igmp**: indicates the line was generated by the `watch_igmp` command passing the `acc-igmp` tag as the first argument, at the bottom of [ingest-troubleshoot.sh](ingest-troubleshoot.sh).
 - **igmp v3 report**: indicates the packet is an IGMPv3 membership report
 - **gaddr 232.1.1.1 allow { 23.212.185.4 }**: indicates the packet is asking the network to subscribe to the (S,G) with source 23.212.185.4 and group 232.1.1.1.

In some misconfigured or constrained networks, starting a receiver that joins might see an IGMPv2 report without a source address instead of an IGMPv3 report.
The normal ingest platform requires the use of SSM, but networks that need a workaround at this stage can consider using [MNAT](https://github.com/GrumpyOldTroll/mnat).

### PIM SSM Joins

The sample-troubleshoot.log file examined in the rest of this walkthrough excluded the watch_pim calls to make a smaller log file that didn't have as much junk in it, but an extra earlier run for 23.212.185.5 (instead of .4) to 232.1.1.1 is also included in [sample-troubleshoot-with-pim.log](sample-troubleshoot-with-pim.log) with some extra debugging enabled, to provide samples for this section.

When the join gets advertised to the network successfully with IGMP/MLD, the [sample-network](sample-network) propagates the request as a [PIM](https://www.rfc-editor.org/rfc/rfc7761.html) Join message along the reverse path toward the route to the source address.
The network needs to be configured so that that reverse path lands at the ingest device (e.g. by the use of a command like [ip mroute](https://www.cisco.com/c/m/en_us/techdoc/dc/reference/cli/nxos/commands/pim/ip-mroute.html) to configure the next-hop router's MRIB to use the ingest device as the default route for multicast RPF lookups).

At [line 37](sample-troubleshoot-with-pim.log#L37) of sample-troubleshoot-with-pim.log, we see the PIM join packet propagating uptream from the access-rtr (the nearest router to the receiver):

~~~
acc-pim      16:51:40 	Join / Prune, cksum 0x1006 (correct), upstream-neighbor: 10.8.1.1
acc-pim      16:51:40 	  1 group(s), holdtime: 3m30s
acc-pim      16:51:40 	    group #1: 232.1.1.1, joined sources: 1, pruned sources: 0
acc-pim      16:51:40 	      joined source #1: 23.212.185.5(S)
~~~

At [line 31](sample-troubleshoot-with-pim.log#L31) of sample-troubleshoot-with-pim.log, we see a nearly identical PIM join packet propagating into the ingest platform:

~~~
ing-pim      16:51:40 	Join / Prune, cksum 0x1003 (correct), upstream-neighbor: 10.9.1.3
ing-pim      16:51:40 	  1 group(s), holdtime: 3m30s
ing-pim      16:51:40 	    group #1: 232.1.1.1, joined sources: 1, pruned sources: 0
ing-pim      16:51:40 	      joined source #1: 23.212.185.5(S)
~~~

These diagnostic lines were both generated with the following command, from inside the `watch_pim` function in [ingest-troubleshoot.sh](ingest-troubleshoot.sh#L98):

~~~
tcpdump -i $IFACE -n -vvv pim
~~~

If a packet like this arrives at the ingest device, it means the network has successfully informed the ingest device about the (S,G) joined by a receiver.
It also generally means the forwarding is properly set up through the network.

### Container Reactions

Once a PIM Join has reached the ingest device, there are several new opportunities for things to go wrong, and what to fix depends on which one it was.

The expected chain of events looks like:

 1. `pimwatch` sees the join and merges it into the joinfile it outputs
 2. `cbacc` sees the edit to the joinfile from `pimwatch`, checks for exceeding the bandwidth limits, and updates the joinfile it outputs
 3. `driad-ingest` sees the edit to the joinfile from `cbacc`, finds the right relay, launches `amtgw` connecting to it, and communicate the group membership to the relay over the AMT tunnel.

All the lines that appear in the [log](sample-troubleshoot.log) with the `watcher`, `cbacc`, and `driad` tags as the first word of the line were generated by calling `docker logs --since 1s -f $CONTAINER` from inside the [watch_container](ingest-troubleshoot.sh#L56) function on the ingest device.

#### pimwatch

The relevant pimwatch log lines at [line 32](sample-troubleshoot.log#L32) looks like this:

~~~
watcher      16:04:32 00:04:32.038 Received PIM JOIN/PRUNE from 10.9.1.1 on eth0
watcher      16:04:32 00:04:32.038 Received PIM JOIN from 10.9.1.1 to group 232.1.1.1 for source 23.212.185.4 on eth0
watcher      16:04:32 00:04:32.038 move_kernel_cache: SG
watcher      16:04:32 00:04:32.038 move_kernel_cache: SG
watcher      16:04:32 00:04:32.039 Added kernel MFC entry src 23.212.185.4 grp 232.1.1.1 from eth1 to eth0
~~~

This is output from [pimd](https://github.com/troglobit/pimd/blob/4507d7c76fc6665eede7704b82b0598b29845159/src/kern.c#L491) indicating that the forwarding path was set up in the kernel for this (S,G).

It's marked by the **watcher** tag as given as the first argument to the `watch_container` function call in [ingest-troubleshoot.sh](ingest-troubleshoot.sh#L94).

These lines report that it has seen the join for 23.212.185.4->232.1.1.1 and is including it in its output joinfile.

The other important pieces come from [pimwatch](pimwatch/pimwatch.py), where the joinfile is managed so that cbacc (or driad-ingest, if not running cbacc) can consume it.

The relevant pimwatch log lines at [line 42](sample-troubleshoot.log#L42) look like this:

~~~
watcher      16:04:35 2021-02-04 00:04:35,186[INFO]: adding new sg: 23.212.185.4->232.1.1.1
watcher      16:04:35 2021-02-04 00:04:35,189[INFO]: launching join for (IPv4Address('23.212.185.4'), IPv4Address('232.1.1.1'))
watcher      16:04:35 2021-02-04 00:04:35,196[INFO]: live sg refreshed: 23.212.185.4->232.1.1.1
~~~

Near the end at [line 152](sample-troubleshoot.log#L152) the container does the inverse operation, removing the (S,G) from its output joinfile in response to a prune message (causing a similar reversal in the cbacc and driad-ingest containers):

~~~
watcher      16:05:01 00:05:01.542 Received PIM JOIN/PRUNE from 10.9.1.1 on eth0
watcher      16:05:01 00:05:01.542 Received PIM PRUNE from 10.9.1.1 to group 232.1.1.1 for source 23.212.185.4 on eth0
watcher      16:05:01 00:05:01.542 find_route: exact (S,G) entry for (23.212.185.4,232.1.1.1) found
watcher      16:05:05 2021-02-04 00:05:05,904[INFO]: removing live sg: 23.212.185.4->232.1.1.1
watcher      16:05:05 2021-02-04 00:05:05,906[INFO]: stopping sg 23.212.185.4->232.1.1.1
~~~

This container runs [pimwatch-start](pimwatch/docker/pimwatch-start.py) to launch both [pimd](https://github.com/troglobit/pimd) and [pimwatch](pimwatch/pimwatch.py), so generally the log lines come from one of those processes.

#### cbacc

The relevant cbacc log lines at [line 47](sample-troubleshoot.log#L47) look like this:

~~~
cbacc        16:04:35 2021-02-04 00:04:35,197[INFO]: got sgs update: {(IPv4Address('23.212.185.4'), IPv4Address('232.1.1.1'))}
cbacc        16:04:35 2021-02-04 00:04:35,738[INFO]: fetching cbacc info with https://disrupt-dorms.edgesuite.net/restconf/data/ietf-dorms:metadata/sender=23.212.185.4/group=232.1.1.1/ietf-cbacc:cbacc
cbacc        16:04:35 2021-02-04 00:04:35,782[INFO]: none blocked (1 flows with 0.00191mb) active and (0) held down from prior block: set()
~~~

When joining an (S,G) would put the cbacc joinfile over the total bandwidth limit, some (S,G)s will be blocked according to the [fairness function](https://datatracker.ietf.org/doc/html/draft-ietf-mboned-cbacc-02#section-2.3.2) implemented in [cbacc-mgr](cbacc/cbacc-mgr.py#L283).

Lines emitted by this container are marked by the **cbacc** tag as given as the first argument to the `watch_container` function call in [ingest-troubleshoot.sh](ingest-troubleshoot.sh#L95).

#### driad-ingest

The relevant driad-ingest log lines at [line 50](sample-troubleshoot.log#L50) look like this:

~~~
driad        16:04:35 2021-02-04 00:04:35,787[INFO]: adding new sg: 23.212.185.4->232.1.1.1
driad        16:04:35 2021-02-04 00:04:35,788[INFO]: finding relay ip for 23.212.185.4
driad        16:04:35 2021-02-04 00:04:35,908[INFO]: found relay option prec=16,d=0,typ=3,val=r4v4.amt.akadns.net.
driad        16:04:35 2021-02-04 00:04:35,909[INFO]: randomly chose idx 0 of 1 relay options
driad        16:04:36 2021-02-04 00:04:36,038[INFO]: found relay ip 13.56.226.127 for src 23.212.185.4
driad        16:04:36 2021-02-04 00:04:36,039[INFO]: launching gateway to relay 13.56.226.127
driad        16:04:36 2021-02-04 00:04:36,039[INFO]: running: /usr/bin/docker create --rm --name ingest-gw-13.56.226.127 --privileged --log-opt max-size=2m --log-opt max-file=5 --network amt-bridge grumpyoldtroll/amtgw:0.0.4 13.56.226.127
driad        16:04:36 2021-02-04 00:04:36,332[INFO]: running: /usr/bin/docker network connect mcast-native-ingest ingest-gw-13.56.226.127
driad        16:04:37 2021-02-04 00:04:37,531[INFO]: running: /usr/bin/docker start ingest-gw-13.56.226.127
driad        16:04:38 2021-02-04 00:04:38,881[INFO]: launching join for (IPv4Address('23.212.185.4'), IPv4Address('232.1.1.1'))
driad        16:04:38 2021-02-04 00:04:38,882[INFO]: running /usr/bin/stdbuf -oL -eL /bin/ssm-stay-joined 23.212.185.4 232.1.1.1 65534
~~~

This describes noticing the (S,G) from the joinfile produced by cbacc, discovering the relay with a [DRIAD](https://www.rfc-editor.org/rfc/rfc8777.html)-style AMTRELAY DNS query, and launching the corresponding amtgw container to connect to the relay, plus advertising the join into the tunnel.

### Data Traffic

Once the AMT relay is launched, some AMT traffic and some native multicast traffic should show up in the logs.

The ingest-troubleshoot.sh functions for [watch_traffic](ingest-troubleshoot.sh#L59) and [watch_amt](ingest-troubleshoot.sh#L73) limit the count of packets to avoid spamming the log for high rate streams, but still showing that traffic was flowing at the given points in the network.

The AMT traffic is received as UDP by a particular `amtgw` container instance, then the native multicast data traffic is forwarded in the `mcast-native-ingest` docker network, which gets forwarded onto `downstream-mcast` because of the multicast routing set up by the `pimd` instance running inside `pimwatch`.

Since the `downstream-mcast` network is connected to an interface on the downstreqm network, the native traffic then should get sent through the network toward the receiver.

The sample-troubleshoot.log file has 3 different tags relevant to the data traffic observed:

 - **amt**: the AMT traffic between an `amtgw` instance and a remote AMT relay
 - **traffic-in**: the native UDP data traffic seen emitted from the ingest device
 - **traffic-acc**: the native UDP data traffic that reaches the access network connected to the receiver.

#### AMT

The AMT traffic up to the first data packet appears at [line 60](sample-troubleshoot.log#L60):

~~~
amt          16:04:40 00:04:39.948315 IP 10.9.1.3.59526 > 13.56.226.127.2268: UDP, length 8
amt          16:04:40 00:04:39.983137 IP 13.56.226.127.2268 > 10.9.1.3.59526: UDP, length 12
amt          16:04:40 00:04:39.984126 IP 10.9.1.3.41265 > 13.56.226.127.2268: UDP, length 8
amt          16:04:40 00:04:39.984282 IP 10.9.1.3.41265 > 13.56.226.127.2268: UDP, length 8
amt          16:04:40 00:04:40.011496 IP 13.56.226.127.2268 > 10.9.1.3.41265: UDP, length 44
amt          16:04:40 00:04:40.011499 IP 13.56.226.127.2268 > 10.9.1.3.41265: UDP, length 44
amt          16:04:40 00:04:40.012415 IP 10.9.1.3.41265 > 13.56.226.127.2268: UDP, length 60
amt          16:04:40 00:04:40.012623 IP 10.9.1.3.41265 > 13.56.226.127.2268: UDP, length 72
amt          16:04:40 00:04:40.143326 IP 10.9.1.3.41265 > 13.56.226.127.2268: UDP, length 8
amt          16:04:40 00:04:40.171184 IP 13.56.226.127.2268 > 10.9.1.3.41265: UDP, length 44
amt          16:04:40 00:04:40.171963 IP 10.9.1.3.41265 > 13.56.226.127.2268: UDP, length 56
amt          16:04:40 00:04:40.271085 IP 10.9.1.3.41265 > 13.56.226.127.2268: UDP, length 8
amt          16:04:40 00:04:40.295596 IP 13.56.226.127.2268 > 10.9.1.3.41265: UDP, length 44
amt          16:04:40 00:04:40.296264 IP 10.9.1.3.41265 > 13.56.226.127.2268: UDP, length 72
amt          16:04:40 00:04:40.522767 IP 13.56.226.127.2268 > 10.9.1.3.41265: UDP, length 155
~~~

It's marked by the **amt** tag, as passed as the first argument to the `watch_amt` function in [ingest-troubleshoot.sh](ingest-troubleshoot.sh#L100).

The output comes from running `tcpdump -i $IFACE -n -c 40 udp port 2268` (2268 is the [UDP port number for AMT](https://www.rfc-editor.org/rfc/rfc7450.html#section-7.2) traffic).

The packets of length 8, 12, 44, 60, and 72 are the AMT handshake and group membership request/report packets.  The 72 length can vary when there are multiple groups joined, and in general they can vary some when connecting to different relays.  They also will have different values when using IPv6.  But in general, those starting and periodically refreshing control packets have nothing to do with the size of the data packets.

The packets of length 155 are 155 because the data packets for this stream are length 125, and those get encapsulated with an extra IP header (20 bytes), an extra UDP header (8 bytes), and an AMT Data header (2 bytes).
When receiving traffic of a different size, the AMT packet sizes will vary with the data packet size, adding that same overhead (or a larger number for IPv6, reflecting the larger header size).

#### Native Multicast Traffic

The sample script shows traffic in 2 locations.  The first log line showing a data packet emitted by the ingest platform is at [line 68](sample-troubleshoot.log#L68) and looks like this:

~~~
traffic-in   16:04:40 00:04:40.526740 IP 23.212.185.4.5001 > 232.1.1.1.5001: UDP, length 125
~~~

That's marked with **traffic-in**, as passed as the first parameter to the `watch_traffic` function at [line 101](ingest-troubleshoot.sh#L101) of ingest-troubleshoot.sh.

The first log line showing a data packet forwarded on the LAN connected to the receiver is at [line 84](sample-troubleshoot.log#L84) and looks like this:

~~~
traffic-acc  16:04:41 00:04:40.523571 IP 23.212.185.4.5001 > 232.1.1.1.5001: UDP, length 125
~~~

That's marked with **traffic-acc**, as passed as the first parameter to the `watch_traffic` function at [line 102](ingest-troubleshoot.sh#L102) of ingest-troubleshoot.sh.

The `watch_traffic` function outputs lines from `tcpdump -i $IFACE -n -c 10 udp and net 224.0.0.0/4`.

# Resources

I maintain a few live streams.  These may not remain up forever, so if they seem down, contact me and I can possibly launch them again or point you to an updated location.

 * with [iperf-ssm](https://github.com/GrumpyOldTroll/iperf-ssm) (1kbps): iperf --server --udp --bind 232.1.1.1 --source 23.212.185.5 --interval 1 --len 1500 --interface en5
 * with [vlc](https://www.videolan.org/index.html) (about 5mbps, streaming [blender project](https://www.blender.org/about/projects/) videos): vlc udp://23.212.185.5@232.10.10.2:12000

Akamai also has some proprietary receivers and corresponding source streams that are under development.  [Contact me](mailto:jholland@akamai.com) if you would like to arrange to do some experiments or trials.

## Internet2

There are also a number of video streams active on [internet2](https://www.internet2.edu/) and reachable by some AMT relays.

 * Lauren Delwiche wrote and maintains a [menu of content](https://multicastmenu.herokuapp.com/) app
 * William Zhang has published a [scanning script](https://github.com/willzhang05/senior-research/blob/master/find_src_i2.py) to find live multicast streams on I2 by scraping the [Routing Table Proxy](https://routerproxy.wash2.net.internet2.edu/routerproxy/) published by [Indiana University](https://routerproxy.wash2.net.internet2.edu/).
 * Lenny Giuliano maintains a "[MTTG](https://www.ietf.org/proceedings/104/slides/slides-104-mboned-mttg-01)" (Multicast to the Grandma) slack server where you can learn about all this and more.  If you'll be working in this space and you want to get in touch with the people driving this technology, contact me (open an issue if you like, or my email is in some of the specs linked above) and I can get you an invite.

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

