#!/bin/bash


# cleanup:
# sudo docker image ls | tail -n +2 | grep '<none>' | awk '{print $3;}' | xargs -n 1 sudo docker image rm

# jake 2020-01-14: pretty sure i'm doing this wrong, but note to self:
# remember to update README.md
VERSION=0.0.4

for NAME in pimwatch driad-ingest cbacc ; do
  IMG=$(sudo docker image ls $NAME:latest | grep latest | awk '{print $3;}')
  sudo docker tag $IMG grumpyoldtroll/$NAME:$VERSION
  sudo docker push grumpyoldtroll/$NAME:$VERSION
  sudo docker push grumpyoldtroll/$NAME:latest
done

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

