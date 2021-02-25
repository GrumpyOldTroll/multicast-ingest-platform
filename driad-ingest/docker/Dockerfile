FROM ubuntu:focal

RUN apt-get update && apt-get install -y \
    build-essential \
    autoconf libtool-bin make \
    git

RUN git -c advice.detachedHead=false clone -b 0.0.2 --depth 1 https://github.com/GrumpyOldTroll/libmcrx /tmp/libmcrx
RUN cd /tmp/libmcrx && ./autogen.sh && ./configure && make

FROM ubuntu:focal
LABEL maintainer="jholland@akamai.com"

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
  apt-get install -y \
    python3 \
    python3-pip \
    docker.io \
    dnsutils

RUN pip3 install watchdog

COPY --from=0 /tmp/libmcrx/mcrx-check /usr/bin/mcrx-check

RUN mkdir -p /var/run/ingest/ && touch /var/run/ingest/joined.sgs

COPY driad-ingest/docker/driad-start /bin/driad-ingest-start
COPY driad-ingest/driad-ingest-mgr /bin/driad-ingest-mgr

ENTRYPOINT ["/bin/driad-ingest-start"]

