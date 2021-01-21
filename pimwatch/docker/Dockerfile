#FROM troglobit/pimd:2.3.2

FROM alpine:3.9
RUN apk add --update git build-base automake autoconf linux-headers

RUN apk add --update pkgconfig

RUN git clone --depth=1 https://github.com/troglobit/pimd.git /root/pimd
WORKDIR /root/pimd
RUN ./autogen.sh
RUN ./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var
RUN make
RUN make install-strip DESTDIR=/tmp

FROM alpine:3.9
RUN apk add python3 coreutils tcpdump
RUN ln -s /usr/sbin/tcpdump /usr/bin/tcpdump

COPY --from=0 /tmp/usr/sbin/pimd /tmp/usr/sbin/pimctl /usr/sbin/
COPY pimwatch/pimwatch.py /usr/sbin/pimwatch.py
COPY pimwatch/docker/pimwatch-start.py /usr/sbin/pimwatch-start

ENTRYPOINT [ "/usr/sbin/pimwatch-start" ]

