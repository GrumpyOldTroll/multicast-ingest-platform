# Building your own FRR image

You need git if you don't have it:

~~~
sudo apt install -y git
~~~

## Pull source, make branch

A few useful links, if you want to know more:

 * <https://github.com/FRRouting/frr>
 * <http://docs.frrouting.org/projects/dev-guide/en/latest/building-frr-for-alpine.html>
 * <https://hub.docker.com/r/cumulusnetworks/frrouting/>

~~~
git clone https://github.com/FRRouting/frr.git
cd frr
git checkout tags/frr-6.1-dev
~~~

## Build docker image

Repeat as needed, when you make changes to the source in your local file system.

~~~
docker/alpine/build.sh
docker build --rm -f docker/alpine/Dockerfile -t local-build-mip-frr:latest .
docker save --output local-build-mip-frr.tar local-build-mip-frr:latest
~~~

If successful, this produces local-build-mip-frr.tar, which you can copy to whichever routers need it.  (gzipping may be worthwhile; compresses from about 100mb to about 40mb).

## Load image on other machines

~~~
docker load --input local-build-mip-frr.tar
docker image ls local-build-mip-frr:latest
~~~
