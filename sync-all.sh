#!/bin/bash

# with something like this running:
# ssh -nN -L 7050:10.7.1.50:22 -L 8111:10.8.1.1:22 -L 8112:10.8.1.2:22 -L 9112:10.9.1.2:22 user@192.168.7.167

set -x

for PORT in 9212; do
	rsync -crvz --exclude=.git/ --exclude=".*.sw?" -e "ssh -p $PORT -l user" ~/src/github/multicast-ingest-platform/ localhost:mip/
done

