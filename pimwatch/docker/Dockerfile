#FROM troglobit/pimd:2.3.2

FROM ubuntu:focal

RUN apt-get update && apt-get install -y \
    build-essential \
    autoconf libtool-bin make \
    git

RUN git clone --depth=1 https://github.com/troglobit/pimd.git /root/pimd
WORKDIR /root/pimd
RUN ./autogen.sh
RUN ./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var
COPY pimwatch/docker/pimd-hack.patch /tmp/
RUN patch -p1 -i /tmp/pimd-hack.patch
RUN make
RUN make install-strip DESTDIR=/tmp

FROM ubuntu:focal
LABEL maintainer="jholland@akamai.com"

RUN apt-get update && \
  apt-get install -y \
    python3 \
    python3-pip \
    tcpdump \
    iproute2

COPY --from=0 /tmp/usr/sbin/pimd /tmp/usr/sbin/pimctl /usr/sbin/
COPY pimwatch/pimwatch.py /usr/sbin/pimwatch.py
COPY pimwatch/docker/pimwatch-start.py /usr/sbin/pimwatch-start

ENTRYPOINT [ "/usr/sbin/pimwatch-start" ]

