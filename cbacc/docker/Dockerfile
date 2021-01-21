FROM ubuntu:focal
LABEL maintainer="jholland@akamai.com"

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
  apt-get install -y \
    python3 \
    python3-pip \
    docker.io \
    dnsutils

RUN pip3 install \
  watchdog \
  requests \
  requests_cache \
  dnspython

RUN mkdir -p /var/run/cbacc-in/ && mkdir -p /var/run/cbacc-out/

COPY cbacc/cbacc-mgr.py /bin/cbacc-mgr.py
COPY cbacc/cbacc-info.py /bin/cbacc-info.py

ENTRYPOINT ["/bin/cbacc-mgr.py"]

