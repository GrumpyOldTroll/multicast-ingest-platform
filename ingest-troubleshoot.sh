#!/usr/bin/bash

# set -x

TAGGED_PS=""
function tagged_remote() {
	local ID=$1
	local LOC=$2
	local CMD=$3

  echo "${ID}: at $(date +"%Y-%m-%d %H:%M:%S") on ${LOC}, running: ${CMD}"
	stdbuf -oL -eL ssh -T ${LOC} "date +'%Y-%m-%d %H:%M:%S' ; stdbuf -oL -eL ${CMD} 2>&1" | stdbuf -oL -eL awk "{printf \"%-12s %s %s\\n\", \"${ID}\", strftime(\"%H:%M:%S\"), \$0; }" &
	TAGGED_PS="${TAGGED_PS} $!"
}

function watch_igmp () {
	local ID=$1
	local LOC=$2
	local IFACE=$3
	if [ "${ID}" = "" -o \
		"${LOC}" = "" -o \
		"${IFACE}" = "" ]; then
		echo "watch_igmp bad args: ID='${ID}', LOC='${LOC}', IFACE='${IFACE}'"
		return -1
	fi
	tagged_remote $ID $LOC "sudo stdbuf -oL -eL tcpdump -i ${IFACE} -n -vvv igmp"
}

function watch_pim () {
	local ID=$1
	local LOC=$2
	local IFACE=$3
	if [ "${ID}" = "" -o \
		"${LOC}" = "" -o \
		"${IFACE}" = "" ]; then
		echo "watch_pim bad args: ID='${ID}', LOC='${LOC}', IFACE='${IFACE}'"
		return -1
	fi
	echo "${ID}=watch_pim for ${LOC} on ${IFACE}"
	# for ip4 without ip options, exclude hello with: "ip[20]&0xf != 0", but would be nice if
	# they had a "ip.payload[0]" instead of ip[20]
	tagged_remote $ID $LOC "sudo stdbuf -oL -eL tcpdump -i ${IFACE} -n -vvv pim"
}

function watch_container () {
	local ID=$1
	local LOC=$2
	local CONTAINER=$3
	if [ "${ID}" = "" -o \
		"${LOC}" = "" -o \
		"${CONTAINER}" = "" ]; then
		echo "watch_container bad args: ID='${ID}', LOC='${LOC}', CONTAINER='${CONTAINER}'"
		return -1
	fi
	echo "${ID}=watch_container for ${LOC} on ${CONTAINER}"
	tagged_remote $ID $LOC "sudo stdbuf -oL -eL docker logs --since 1s -f ${CONTAINER}"
}

function watch_traffic () {
	local ID=$1
	local LOC=$2
	local IFACE=$3
	if [ "${ID}" = "" -o \
		"${LOC}" = "" -o \
		"${IFACE}" = "" ]; then
		echo "watch_traffic bad args: ID='${ID}', LOC='${LOC}', IFACE='${IFACE}'"
		return -1
	fi
	echo "${ID}=watch_traffic for ${LOC} on ${IFACE}"
	tagged_remote $ID $LOC "sudo stdbuf -oL -eL tcpdump -i ${IFACE} -c 10 -n udp and net 224.0.0.0/4"
}

function watch_amt () {
	local ID=$1
	local LOC=$2
	local IFACE=$3
	if [ "${ID}" = "" -o \
		"${LOC}" = "" -o \
		"${IFACE}" = "" ]; then
		echo "watch_amt bad args: ID='${ID}', LOC='${LOC}', IFACE='${IFACE}'"
		return -1
	fi
	echo "${ID}=watch_amt for ${LOC} on ${IFACE}"
	tagged_remote $ID $LOC "sudo stdbuf -oL -eL tcpdump -i ${IFACE} -c 40 -n udp port 2268"
}


INGEST=user@10.9.1.3
INGEST_PHYS=irf0
ACCESS=user@10.7.1.1
ACCESS_PHYS=xdn0

# function      tag/name    login     (container/interface)
watch_container watcher     ${INGEST} pimwatch
watch_container cbacc       ${INGEST} cbacc
watch_container driad       ${INGEST} driad-ingest
watch_igmp      acc-igmp    ${ACCESS} xdn0
#watch_pim       acc-pim     ${ACCESS} xup0
#watch_pim       ing-pim     ${INGEST} ${INGEST_PHYS}
watch_amt       amt         ${INGEST} ${INGEST_PHYS}
watch_traffic   traffic-in  ${INGEST} ${INGEST_PHYS}
watch_traffic   traffic-acc ${ACCESS} xdn0

echo "pids of watchers:${TAGGED_PS}"

trap "trap - SIGTERM && kill -- -$$" SIGINT SIGTERM EXIT
wait ${TAGGED_PS}

