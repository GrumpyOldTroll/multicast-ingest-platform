FROM ubuntu:focal

RUN apt-get update && apt-get install -y \
    build-essential \
    autoconf libtool-bin make \
    git

RUN git clone https://github.com/GrumpyOldTroll/libmcrx /tmp/libmcrx
RUN cd /tmp/libmcrx && ./autogen.sh && ./configure --enable-static && make
COPY driad-ingest/ssm-stay-joined.c /tmp/
RUN gcc -o /tmp/ssm-stay-joined -isystem /tmp/libmcrx/include /tmp/ssm-stay-joined.c /tmp/libmcrx/src/.libs/libmcrx.a

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

COPY --from=0 /tmp/ssm-stay-joined /bin/ssm-stay-joined

RUN mkdir -p /var/run/ingest/ && touch /var/run/ingest/joined.sgs

COPY driad-ingest/docker/driad-start /bin/driad-ingest-start
COPY driad-ingest/driad-ingest-mgr /bin/driad-ingest-mgr

ENTRYPOINT ["/bin/driad-ingest-start"]

