#!/bin/bash

set -x
set -e

if [ -d /usr/lib/frr ]; then
  echo "frr already installed, skipping frr build/install"
  exit 0
fi

MAJ=$(lsb_release --release --short | cut -f1 -d.)
if [ "$MAJ" -lt "20" ]; then
	PYTHON2=python
else
	PYTHON2=python2
fi

sudo bash -x -e << EOF
add-apt-repository universe

apt-get update

# build & runtime dependencies
apt-get install -y \
  libexpat1-dev \
  libacl1-dev \
  libatomic-ops-dev \
  libattr1-dev \
  libc-ares-dev \
  libcap-dev \
  libgdbm-dev \
  libgmp-dev \
  libjson-c-dev \
  libpcre3-dev \
  libprotobuf-c-dev \
  lib${PYTHON2}-dev \
  libpam0g-dev \
  libsnmp-dev \
  libsystemd-dev \
  libreadline-dev \
  libzmq3-dev \
  libzmq5 \
  pkg-config \
  perl \
  ${PYTHON2} \
  python-ipaddress \
  python3-dev \
  python3-pytest \
  python3-sphinx

# build tools
apt-get install -y \
  autoconf \
  automake \
  bison \
  build-essential \
  cmake \
  flex \
  g++ \
  gcc \
  git \
  install-info \
  libtool \
  make \
  protobuf-c-compiler \
  texinfo
# workaround for weird dependency not available on ubuntu
# libyang required by frr.
# it's coming in sid, not here yet in stretch:
# https://packages.debian.org/sid/libyang-dev
apt-get install -y libyang-dev || /bin/true
EOF

if ! dpkg --list libyang-dev; then
  if [ ! -d libyang ]; then
    git clone https://github.com/CESNET/libyang && \
    git -C libyang checkout tags/v1.0.184
    cd libyang && \
    mkdir build && cd build && \
    cmake -DENABLE_LYD_PRIV=ON -DCMAKE_INSTALL_PREFIX:PATH=/usr \
      -D CMAKE_BUILD_TYPE:String="Release" .. && \
    make && sudo make install && cd .. && rm -rf build && cd ..
  fi
fi

if [ ! -d frr ]; then
  git clone https://github.com/FRRouting/frr
  # My local patches are no longer necessary on branches that include:
  # https://github.com/FRRouting/frr/pull/3863
  # git -C frr checkout tags/frr-7.1-dev
  # patch -p1 -d frr/ -i ../../../jake2.patch --ignore-whitespace
  # patch -p1 -d frr/ -i ../../../jake3.patch --ignore-whitespace
  #git -C frr checkout tags/frr-7.4
  git -C frr checkout tags/frr-7.3.1
fi
cd frr

c=$(git rev-parse --short=10 HEAD)
commit=$(printf '%u\n' 0x$c)

# frr 7.4: python3 seems to need to be explicit because configure
# fails when python2 is used for makefile (-jake 2020-08):
# 
# config.status: creating Makefile
# Traceback (most recent call last):
#   File "/home/user/multicast-ingest-platform/configs/access-rtr/frr/python/makefile.py", line 24, in <module>
#     mv = MakeReVars(before)
#   File "/home/user/multicast-ingest-platform/configs/access-rtr/frr/python/makevars.py", line 73, in __init__
#     super().__init__()
# TypeError: super() takes at least 1 argument (0 given)
#
export PYTHON=/usr/bin/python3

./bootstrap.sh && \
./configure \
    --prefix=/usr \
    --enable-numeric-version \
    --enable-exampledir=/tmp \
    --enable-systemd \
    --enable-vtysh \
    --disable-doc \
    --includedir=\${prefix}/include \
    --bindir=\${prefix}/bin \
    --sbindir=\${prefix}/lib/frr \
    --libdir=\${prefix}/lib/frr \
    --libexecdir=\${prefix}/lib/frr \
    --localstatedir=/var/run/frr \
    --sysconfdir=/etc/frr \
    --with-moduledir=\${prefix}/lib/frr/modules \
    --with-libyang-pluginsdir=\${prefix}/lib/frr/libyang_plugins \
    --enable-configfile-mask=0640 \
    --enable-logfile-mask=0640 \
    --enable-snmp=agentx \
    --enable-multipath=64 \
    --enable-user=frr \
    --enable-group=frr \
    --enable-vty-group=frrvty \
    --with-pkg-git-version \
    --with-pkg-extra-version=_jholland_mip_g$commit && \
make && sudo make install
#make distclean
cd ..

sudo bash -x -e <<EOF
# set up forwarding and frr
echo "net.ipv4.ip_forward=1" | tee -a /etc/sysctl.conf
sysctl -w net.ipv4.ip_forward=1

( addgroup --system --gid 92 frr && \
  addgroup --system --gid 85 frrvty && \
  adduser --system --ingroup frr --home /var/run/frr/ \
     --gecos "FRR suite" --shell /sbin/nologin frr && \
     usermod -a -G frrvty frr ) \
  || echo "frr already set up?"

mkdir -p /var/run/frr && chown frr:frr /var/run/frr

install -m 775 -o frr -g frr -d /var/log/frr
install -m 775 -o frr -g frrvty -d /etc/frr
install -m 640 -o frr -g frr -t /etc/frr etc/frr/*

if [ -f frr/tools/etc/frr ]; then
  install -m 775 -o frr -g frr -d /etc/default/frr
  install -m 640 -o frr -g frr -t /etc/default/frr frr/tools/etc/frr/*
fi
install -m 644 -o root -g root frr/tools/frr.service /lib/systemd/system/frr.service

# hack workaround: frr in 7.4 not producing log files without this.
# --jake 2020-08
sed -i '/\[Service\]/a WorkingDirectory=\/var\/log\/frr' /lib/systemd/system/frr.service

install -m 644 -o root -g root ../logrotate.d/frr /etc/logrotate.d/frr

systemctl enable frr.service
systemctl daemon-reload
EOF

