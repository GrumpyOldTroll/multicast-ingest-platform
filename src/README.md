# Ingest Logic

This section has the implementation of the internal details of the ingest platform's behavior.

## joinfile2ingest.py

The key controller that manages the AMT gateways is joinfile2ingest.py.

This uses [watchdog](https://pypi.org/project/watchdog/) to monitor a "joinfile" that lists the currently joined (S,G)s.  Whenever the file changes, it's reloaded and if the reload parses successfully, relays are discovered for any new sources, and AMT gateways are launched or shut down.

The AMT gateways use the [grumpyoldtroll/amtgw](https://hub.docker.com/r/grumpyoldtroll/amtgw) docker image, and a container is launched for each connection to a relay.

A joinfile is just a json file that lists sources and groups of the joined (S,G)s like so:

~~~
[
  {
    "source": "23.212.185.5",
    "group": "232.1.1.1"
  },
  {
    "source": "129.174.55.131",
    "group": "232.44.15.9"
  }
]
~~~

## pim2joinfile.py

The pim2joinfile script monitors PIM packets and updates a joinfile to match the current join state.  The joinfile is consumed byb joinfile2ingest.py or something else.

