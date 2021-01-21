#!/usr/bin/env python3

import argparse
import subprocess
import sys
import time
import os
import signal

def main(args_in):
    parser = argparse.ArgumentParser(
            description='''
This runs pimd and watches pim messages on the given downstream
interface.  When a join/prune propagates to this instance, a joinfile
is updated for use by the driad-ingest-mgr or related systems, and
a route is installed with smcroutectl to propagate the given (S,G)'s
traffic from the upstream interface.

It needs /var/run/smcroute.sock to configure the routes with
smcroutectl, and expects to use the host network.''')
    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('-j', '--joinfile', required=True,
        help='Name of the file inside the container where (S,G)s will be updated (needs absolute path within the container)')
    '''
    parser.add_argument('-u', '--upstream', required=True,
        help='The interface from which native multicast traffic for joined (S,G)s will be forwarded to downstream')
    parser.add_argument('-d', '--downstream', required=True,
        help='The interface where pimd will run, look for neighbors, and accept join/prune messages')
    '''

    args = parser.parse_args(args_in[1:])
    verbosity = None
    if args.verbose:
        verbosity = '-'+'v'*args.verbose

    upstream = 'eth1'
    downstream = 'eth0'
    os.environ["PYTHONUNBUFFERED"] = "1"

    watch_cmd = [
        '/usr/bin/stdbuf', '-oL', '-eL',
        sys.executable, '/usr/sbin/pimwatch.py',
        '-u', upstream,
        '-d', downstream,
        '-j', args.joinfile,
    ]

    conf = f'''
phyint eth0 enable
phyint eth1 enable
'''

    pimfile = '/etc/pimd.conf'
    with open(pimfile, 'w') as f:
        print(conf, file=f)
    print(f'/etc/pimd.conf:\n{conf}')

    pim_cmd = [
        '/usr/bin/stdbuf', '-oL', '-eL',
        '/usr/sbin/pimd', '-f', pimfile,
        '--foreground', '--disable-vifs',
    ]

    if verbosity:
        watch_cmd.append(verbosity)
        pim_cmd.extend(['--debug=neighbors,rpf,join-prune'])

    # this is needed as a workaround for:
    # https://github.com/docker/for-linux/issues/568
    # it turns out this otherwise takes the "kernel" route as more
    # significant and uses the output interface as the upstream
    # interface, overriding the setting in /etc/frr/staticd.conf
    # /sbin/ip route del default dev eth0
    delrt_cmd = [
            '/sbin/ip', 'route', 'del', 'default', 'dev', 'eth0' ]
    cmd_str = ' '.join(delrt_cmd)
    print(f'running "{cmd_str}")')
    delrt_p = subprocess.Popen(delrt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = delrt_p.communicate()
    if delrt_p.poll() != 0:
        print(f'error ({delrt_p.poll()}) in "{cmd_str}": out="{out}", err="{err}"')
        raise Exception(err)

    addrt_cmd = [
            '/sbin/ip', 'route', 'add', 'default', 'dev', 'eth1' ]
    cmd_str = ' '.join(addrt_cmd)
    print(f'running "{cmd_str}")')
    addrt_p = subprocess.Popen(addrt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = addrt_p.communicate()
    if addrt_p.poll() != 0:
        print(f'error ({addrt_p.poll()}) in "{cmd_str}": out="{out}", err="{err}"')
        raise Exception(err)

    if verbosity:
        watch_cmd.append(verbosity)
        # 'jp' does not work
        pim_cmd.extend(['--debug=interfaces,join-prune,kernel,neighbors,rpf'])

    print(f'running: {" ".join(watch_cmd)}')
    watch_p = subprocess.Popen(watch_cmd)

    print(f'running: {" ".join(pim_cmd)}')
    pim_p = subprocess.Popen(pim_cmd)

    pim_ret, watch_ret = None, None
    while pim_ret is None and watch_ret is None:
        time.sleep(1)
        watch_ret = watch_p.poll()
        pim_ret = pim_p.poll()

    if watch_ret is None:
        watch_p.send_signal(signal.SIGTERM)
        for i in range(15):
            watch_ret = watch_p.poll()
            if watch_ret is not None:
                break
            time.sleep(0.1)
        if watch_ret is None:
            watch_p.kill()
        print(f'pimwatch killed ({watch_ret}) because frr stopped')
    elif pim_ret is None:
        pim_p.send_signal(signal.SIGTERM)
        for i in range(15):
            pim_ret = pim_p.poll()
            if pim_ret is not None:
                break
            time.sleep(0.1)
        if pim_ret is None:
            pim_p.kill()
        print(f'pim killed ({pim_ret}) because pimwatch stopped')

if __name__=="__main__":
    ret = main(sys.argv)
    sys.exit(ret)

