#!/bin/bash

set -x
set -e

if [ -d /usr/lib/frr ]; then
  echo "frr already installed, skipping frr build/install"
  exit 0
fi

sudo bash -x -e << EOF
# build & runtime dependencies
apt-get install -y \
  libexpat1-dev \
  libacl1-dev \
  libatomic-ops-dev \
  libattr1-dev \
  libc-ares-dev \
  libgdbm-dev \
  libgmp-dev \
  libjson-c-dev \
  libpcre3-dev \
  libpython-dev \
  libsystemd-dev \
  libreadline-dev \
  pkg-config \
  python
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
  libtool
# workaround for weird dependency not available on ubuntu
# libyang required by frr.
# it's coming in sid, not here yet in stretch:
# https://packages.debian.org/sid/libyang-dev
apt-get install -y libyang-dev || /bin/true
EOF

if ! dpkg --list libyang-dev; then
  git clone https://github.com/CESNET/libyang && \
    ( cd libyang && \
    mkdir build && cd build && \
    cmake -DCMAKE_INSTALL_PREFIX=/usr -DENABLE_LYD_PRIV=ON .. && \
    make && sudo make install && cd .. && rm -rf build && cd .. )
fi

if [ ! -d frr ]; then
  git clone https://github.com/FRRouting/frr
  # My local patches are no longer necessary on branches that include:
  # https://github.com/FRRouting/frr/pull/3863
  # git -C frr checkout tags/frr-7.1-dev
  # patch -p1 -d frr/ -i ../../../jake2.patch --ignore-whitespace
  # patch -p1 -d frr/ -i ../../../jake3.patch --ignore-whitespace
fi
cd frr

c=$(git rev-parse --short=10 HEAD)
commit=$(printf '%u\n' 0x$c)

./bootstrap.sh && \
./configure \
  --enable-numeric-version \
  --enable-exampledir=/tmp \
  --enable-systemd \
  --disable-doc \
  --prefix=/usr \
  --localstatedir=/var/run/frr \
  --sbindir=/usr/lib/frr \
  --sysconfdir=/etc/frr \
  --with-pkg-extra-version=_git$commit && \
make && sudo make install
#make distclean
cd ..

