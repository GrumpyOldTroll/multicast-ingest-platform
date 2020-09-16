FROM frrouting/frr:v7.3.1
MAINTAINER Jake Holland <jholland@akamai.com>

RUN apk add python3
RUN apk add docker
RUN apk add tcpdump
RUN apk add bind-tools # for dig
RUN apk add coreutils  # for stdbuf
#apk add py3-pip

# workaround:
# when running inside docker tcpdump hits an apparmor profile from
# outside and gets blocked. So I move tcpdump so that it doesn't
# collide with the external location, and then add a link so it can
# still be invoked with the original path. smh.  --jake 2020-09
#
# see: https://github.com/moby/moby/issues/5490
RUN mv /usr/sbin/tcpdump /bin/tcpdump
RUN ln -s /bin/tcpdump /usr/sbin/tcpdump
RUN mkdir /var/log/frr
RUN chown frr:frr /var/log/frr

RUN rm -r /etc/frr/*
COPY frr/* /etc/frr/
RUN chown frr:frr /etc/frr/*

COPY start.sh /usr/bin/start.sh
RUN chmod 0755 /usr/bin/start.sh

COPY pimwatch.py /usr/bin/pimwatch.py

ENTRYPOINT [ "/sbin/tini", "--", "/usr/bin/start.sh" ]

