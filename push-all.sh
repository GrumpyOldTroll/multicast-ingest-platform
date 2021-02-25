#!/bin/bash


# cleanup:
# sudo docker image ls | tail -n +2 | grep '<none>' | awk '{print $3;}' | xargs -n 1 sudo docker image rm

# jake 2020-01-14: pretty sure i'm doing this wrong, but note to self:
# remember to update README.md

set -e
set -x

VERSION=0.0.6

for NAME in pimwatch driad-ingest cbacc ; do
  IMG=$(sudo docker image ls $NAME:latest | grep latest | awk '{print $3;}')
  sudo docker tag $IMG grumpyoldtroll/$NAME:$VERSION
  sudo docker tag $IMG grumpyoldtroll/$NAME:latest
  sudo docker push grumpyoldtroll/$NAME:$VERSION
  sudo docker push grumpyoldtroll/$NAME:latest
done

if false; then
  # these are currently locked at 0.0.4, with that hard value in
  # README.md and in driad-ingest/driad-ingest-mgr

  # these typically don't have a local image, but check
  for NAME in pim-dummy-upstream amtgw ; do
    IMG=$(sudo docker image ls $NAME:latest | grep latest | awk '{print $3;}')
    if [ "${IMG}" = "" ]; then
      IMG=$(sudo docker image ls grumpyoldtroll/$NAME:latest | grep latest | awk '{print $3;}')
      if [ "${IMG}" = "" ]; then
        sudo docker pull grumpyoldtroll/$NAME:latest
      fi
      sudo docker tag grumpyoldtroll/$NAME:latest grumpyoldtroll/$NAME:$VERSION
    fi
    sudo docker push grumpyoldtroll/$NAME:$VERSION
  done
fi

