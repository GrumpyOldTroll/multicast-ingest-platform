#!/usr/bin/python3

import sys
import logging
from ipaddress import ip_address
from dns.resolver import Resolver
import traceback
import requests_cache
from dns.resolver import Resolver
from itertools import groupby
from requests import Request, Session
import re
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import random
import time
import json
import argparse
import signal
from os.path import abspath, dirname, isfile, basename
from enum import Enum
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

logger=None
sgmgr=None

def setup_logger(name, verbosity=0):
    log_level = logging.WARNING
    if verbosity > 1:
        log_level = logging.DEBUG
    elif verbosity > 0:
        log_level = logging.INFO

    # python logging wtf: logger.setLevel doesn't work the obvious way:
    # https://stackoverflow.com/a/59705351/3427357 (-jake 2020-07)
    handler = logging.StreamHandler()
    #formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    formatter = logging.Formatter('%(asctime)s[%(levelname)s]: %(message)s')
    handler.setFormatter(formatter)
    _logger = logging.getLogger(name)
    _logger.addHandler(handler)
    _logger.setLevel(log_level)
    return _logger

class Context(object):
    def __init__(self):
        self.session = None

# https://softwareengineering.stackexchange.com/a/344274
# http://utopia.duth.gr/~pefraimi/research/data/2007EncOfAlg.pdf
def weighted_shuffle(items, weights):
    order = sorted(range(len(items)), key=lambda i: (-random.random() ** (1.0 / weights[i])) if weights[i] > 0 else random.random())
    return [items[i] for i in order]

def discover_dorms(source_ip):
    '''Returns list of dorms server (domain,port), ordered by priority then randomly according to weight'''
    src = ip_address(source_ip)
    name = '_dorms._tcp.' + src.reverse_pointer

    # TBD: dnssec validation - jake 2020-07
    # best MIT-licensed example I could find (does not validate expirations):
    # https://github.com/spesmilo/electrum/blob/6d2aee18d0bc5b68bff4123855f2b77b7efa1f3b/electrum/dnssec.py#L274
    # see also:
    #  https://backreference.org/2010/11/17/dnssec-verification-with-dig/
    #  https://www.internetsociety.org/resources/deploy360/2013/dnssec-test-sites/

    dnsr = Resolver()
    answer = dnsr.resolve(name, 'SRV')
    rrlist = list(answer.rrset)
    preference_ordering = []
    grouped = [(pri,[rr for rr in gr]) for pri,gr in groupby(rrlist, lambda r: r.priority)]
    for pri,rrpri in sorted(grouped, key=lambda v: v[0]):
        preference_ordering.extend([(str(rr.target), str(rr.port)) for rr in weighted_shuffle(rrpri, [it.weight for it in rrpri])])
    return preference_ordering

def find_base_uri(context, source_ip):
    '''takes source ip, returns url prefix for dorms queries.  optionally accepts a requests.Session() object to maintain shared connection'''
    global logger
    servers = discover_dorms(source_ip)
    # TBD: something like asyncio.staggered_race across the server options?
    # for now just search for something satisfactory - jake 2020-07

    session = context.session
    if not session:
        session = Session()
        context.session = session
    api_pre = None
    for domain, port in servers:
        try:
            if domain.endswith('.'):
                domain = domain[:-1]
            if port == "443" or port == "https":
                url_pre = 'https://{domain}'.format(domain=domain)
            else:
                url_pre = 'https://{domain}:{port}'.format(domain=domain, port=port)

            session.headers.update({'Accept': 'application/xrd+xml'})

            hostmeta_url = url_pre + '/.well-known/host-meta'
            resp = session.get(hostmeta_url)
            root = ET.fromstring(resp.text)
            path_base = root.findall('.//{http://docs.oasis-open.org/ns/xri/xrd-1.0}Link[@rel="restconf"]')[0].attrib['href']

            api_pre = url_pre + path_base
            if not api_pre.endswith('/'):
                api_pre += '/'

            session.headers.update({'Accept': 'application/yang-data+json'})
            
            lib_version_uri = api_pre + 'yang-library-version'
            resp = session.get(lib_version_uri)
            lib_version = resp.json()['ietf-restconf:yang-library-version']
            supported_yang_library_versions = set(['2016-06-21'])
            if lib_version not in supported_yang_library_versions:
                logger.warning('{api_pre}yang-library-version is {date} (not in [{supported}]'.format(api_pre=api_pre, date=lib_version, supported=','.join(supported_yang_library_versions)))

            supported_modules_uri = api_pre + 'data/ietf-yang-library:modules-state'
            resp = session.get(supported_modules_uri)
            supported_modules = resp.json()
            mod_list = supported_modules['ietf-yang-library:modules-state']['module']

            mod_info = {}
            for mod in mod_list:
                mod_info[mod['name']] = mod

            supported_dorms_versions = set(['2019-08-25'])
            if mod_info['ietf-dorms']['revision'] not in supported_dorms_versions:
                logger.warning('dorms version is {date} (not in [{supported}]'.format(date=mod_info['ietf-dorms']['revision'], supported=','.join(supported_dorms_versions)))

            supported_cbacc_versions = set(['2021-01-15'])
            if mod_info['ietf-cbacc']['revision'] not in supported_cbacc_versions:
                logger.warning('cbacc version is {date} (not in [{supported}]'.format(date=mod_info['ietf-cbacc']['revision'], supported=','.join(supported_cbacc_versions)))
        except Exception as e:
            logger.warning("got error with {domain}:{err}".format(domain=domain, err=sys.exc_info()[0]))
            logger.info(traceback.format_exc())
            api_pre = None

    if not api_pre:
        if len(servers):
            logger.error("errors on all {N} viable servers: {servers}".format(N=len(servers), servers=','.join(['%s:%s'%(domain,port) for domain,port in servers])))
        else:
            logger.error("no dorms servers found")

    return api_pre

class CbaccVals(object):
    def __init__(self, cb_vals):
        #self.port = int(udp_stream['port'])
        #cb_vals = udp_stream['ietf-cbacc:cbacc']
        # default values, see:
        # https://tools.ietf.org/html/draft-ietf-mboned-cbacc-01#section-3.2
        self.max_bps = int(cb_vals['max-bits-per-second'])
        self.max_mss = int(cb_vals.get('max-mss', '1400'))
        self.rate_window = int(cb_vals.get('data-rate-window', '2000'))
        self.priority = int(cb_vals.get('priority', '256'))

    def __str__(self):
        return json.dumps({
            'max-bits-per-second': self.max_bps,
            'max-mss': self.max_mss,
            'data-rate-window': self.rate_window,
            'priority': self.priority
        })

def fetch_sg_info(ctx, source, group):
    global logger
    api_pre = find_base_uri(ctx, source)
    session = ctx.session
    src_ip=ip_address(source)
    group_ip=ip_address(group)
    url=api_pre+'data/ietf-dorms:metadata/sender={src}/group={grp}/ietf-cbacc:cbacc'.format(src=src_ip.exploded, grp=group_ip.exploded)
    logger.info(f'fetching cbacc info with {url}')
    resp = session.get(url)
    streams = [CbaccVals(resp.json()['ietf-cbacc:cbacc'])]
    return streams

class SummedSG(object):
    def __init__(self, source, group, udp_streams, expire_time, population):
        self.source = source
        self.group = group
        self.udp_streams = udp_streams
        self.expire_time = expire_time
        self.population = population
        self.sg_bw = 0
        self.spoofed = False
        self.hold_down_time = None
        self.priority = min([cbi.priority for cbi in udp_streams])
        for cbi in udp_streams:
            self.sg_bw += cbi.max_bps

class SGManager(object):
    def __init__(self, ctx, output_file, default_bw, max_bw):
        self.default_bw = default_bw
        self.max_bw = max_bw
        self.cur_desired_set = set()
        self.cur_enabled_set = set()
        self.known_sgs = {}
        self.output_file = output_file
        self.ctx = ctx

    def update_sgset(self, sgset, pops):
        global logger
        logger.info(f'got sgs update: {sgset}')
        add_sgs = sgset - self.cur_desired_set
        kept_sgs = self.cur_desired_set.intersection(sgset)
        remove_sgs = self.cur_desired_set - sgset
        changed_pops = dict()

        new_desired_set = add_sgs.union(kept_sgs)
        now = datetime.now()
        for sg in new_desired_set:
            src, grp = sg
            sginfo = self.known_sgs.get(sg)
            if sginfo:
                sgpop = pops.get(sg)
                if sgpop and sginfo.population != sgpop:
                    changed_pops[sg] = sginfo.population
                    sginfo.population = sgpop
            if not sginfo or sginfo.expire_time < now:
                expire_time = now + timedelta(seconds=1800) # TBD: update with cache info instead of hard half-hour?
                streams = None
                try:
                    streams = fetch_sg_info(self.ctx, src, grp)
                except Exception as e:
                    logger.error(f'failed to fetch cbacc data for {sg}: {str(e)}')
                if streams is None:
                    # TBD: think about failed lookups harder.
                    # for now, leave expired values in place if lookup failed
                    # (maybe should depend on the reason for failure? "could
                    # not reach dorms server" means keep old value, but
                    # "reached dorms server, it knows nothing about this
                    # sg" means drop it in spite of estimate?)
                    if not sginfo:
                        sginfo = SummedSG(src, grp, [CbaccVals({'max-bits-per-second':str(self.default_bw)})], expire_time, pops.get(sg, 1))
                        sginfo.total_bw = self.default_bw
                        sginfo.spoofed = True
                        self.known_sgs[sg] = sginfo
                else:
                    sginfo = SummedSG(src, grp, streams, expire_time, pops.get(sg, 1))
                    self.known_sgs[sg] = sginfo

        for sg in remove_sgs:
            src, grp = sg
            sginfo = self.known_sgs.get(sg)
            if sginfo and sginfo.expire_time < now:
                del(self.known_sgs[sg])

        held_down = set()
        next_wake_time = now + timedelta(seconds=86400)
        desired_rate = 0
        for sg in new_desired_set:
            sginfo = self.known_sgs[sg]
            if sginfo.expire_time < next_wake_time:
                next_wake_time = sginfo.expire_time
            if sginfo.hold_down_time:
                if sginfo.hold_down_time < now:
                    held_down.add(sg)
                    continue
                else:
                    sginfo.hold_down_time = None
            desired_rate += sginfo.sg_bw

        if desired_rate <= self.max_bw:
            # all desired flows are admitted, yay.
            blocked_set = set()
            logger.info(f'none blocked ({len(new_desired_set)} flows with {desired_rate/(1024*1024):.3g}mb) active and ({len(held_down)}) held down from prior block: {held_down}')
        else:
            desire_gap = desired_rate - self.max_bw
            ordering = []
            source_batches = dict()
            for sg in new_desired_set:
                src,grp = sg
                sginfo = self.known_sgs[sg]
                grps = source_batches.get(src)
                if grps is None:
                    grps = dict()
                    source_batches[src] = grps
                grps[grp] = sginfo

                # offload is most important.  biggest offload is kept.
                # for the same offload, smaller stream is better to keep.
                offload = (sginfo.population - 1)*sginfo.sg_bw
                stream_size = sginfo.sg_bw
                on_already = 0
                if sg in self.cur_enabled_set:
                    # favor the ones already on, all else equal (so put
                    # them towards the back)
                    # (TBD: maybe offload should be estimated in buckets
                    # instead of a strict calc from the pop*bw to make this
                    # more stable?)
                    on_already = -1

                ordering.append((offload, stream_size, on_already, sginfo))

            blocked_sgis = []
            blocked_bw = 0
            for offload, stream_size, on, sginfo in reversed(sorted(ordering, key=lambda x: (x[0],x[1],x[2]))):
                blocked_sgis.append(sginfo)
                blocked_bw += sginfo.sg_bw
                if blocked_bw >= desire_gap:
                    break

            min_blocked_bw = min([sgi.sg_bw for sgi in blocked_sgis])
            blocked_set = set([(sgi.source,sgi.group) for sgi in blocked_sgis])
            implied_blocks = set()
            implied_order = []
            implied_bw = 0
            for sginfo in blocked_sgis:
                for grp, other_sginfo in source_batches[sginfo.source].items():
                    if other_sginfo.priority < sginfo.priority:
                        other_sg = (other_sginfo.source,other_sginfo.group)
                        if other_sg not in implied_blocks:
                            logger.info(f'{other_sg} (pri {other_sginfo.priority}, {other_sginfo.sg_bw/(1024*1024):.3g}MiB) implied blocked by {(sginfo.source,sginfo.group)} (pri {sginfo.priority})')
                            implied_blocks.add(other_sg)
                            implied_order.append(other_sg)
                            if other_sg not in blocked_set:
                                implied_bw += other_sg.sg_bw

            if implied_bw >= min_blocked_bw:
                allowed = 0
                for maybe_allow in reversed(blocked_sgis):
                    if implied_bw <= maybe_allow.sg_bw:
                        maybe_sg = (maybe_allow.source,maybe_allow.group)
                        if maybe_sg not in implied_blocks:
                            implied_bw -= maybe_allow.sg_bw
                            blocked_set.remove(maybe_sg)
                            logger.info('{maybe_sg} ({maybe_allow.sg_bw/(1024*1024):.3g}MiB) permitted due to extra space from implied blocks')
                            allowed += 1
                            if implied_bw < min_blocked_bw:
                                break
                if allowed:
                    # order is now broken, but it's ok we don't need it anymore
                    blocked_sgis = [self.known_sgs[sg] for sg in blocked_set]

            hold_down = now + timedelta(seconds=150)
            for sgi in blocked_sgis:
                sgi.hold_down_time = hold_down

            if blocked_sgis:
                logger.info(f'blocked {len(blocked_sgis)}:\n   '+'\n   '.join([f'{sgi.source},{sgi.group}' for sgi in blocked_sgis]))


            '''
            # this kind of fails and added a TBD to the cbacc spec.
            # aggregating by sources is kind of weird.
            # aggregate by source ips
            source_rate = dict()
            for sg in self.cur_desired_set:
                src,grp = sg
                sginfo = self.known_sgs[sg]
                sr = source_rate.get(src)
                if not sr:
                    sr = SummedSource(src)
                    source_rate[src] = sr
                sr.src_bw += sginfo.sg_bw
                sr.groups.append(grp)
            '''

        allowed_sgs = []
        for sg in new_desired_set:
            sginfo = self.known_sgs[sg]
            if sg not in blocked_set:
                if sginfo.hold_down_time:
                    if sginfo.hold_down_time < next_wake_time:
                        next_wake_time = sginfo.hold_down_time
                else:
                    allowed_sgs.append(sg)

        output = '\n'.join([f'{src},{grp}' for src,grp in allowed_sgs])
        with open(self.output_file, 'w') as f:
            print(output, file=f)

        logger.debug('wrote:\n'+output)

        self.cur_desired_set = new_desired_set
        self.cur_enabled_set = set(allowed_sgs)

def on_created_handler(channels, input_file):
    def on_created(event):
        global logger
        logger.debug(f'on_created({event})')
        if event.src_path.endswith(input_file):
            read_joinfile(event.src_path, channels)
    return on_created

def on_moved_handler(channels, input_file):
    def on_moved(event):
        global logger
        logger.debug(f'on_moved({event})')
        if event.dest_path.endswith(input_file):
            read_joinfile(event.dest_path, channels)
    return on_moved

def on_modified_handler(channels, input_file):
    def on_modified(event):
        global logger
        logger.debug(f'on_modified({event})')
        if event.src_path.endswith(input_file):
            read_joinfile(event.src_path, channels)
    return on_modified

def read_joinfile(fname, sgmgr):
    global logger
    sgs = set()
    pops = dict()
    with open(fname) as f:
        line_num = 0
        for in_line in f:
            line = in_line.strip()
            line_num += 1
            if not line:
                continue
            if line.startswith('#'):
                continue
            sg = tuple(v.strip() for v in line.split(','))
            try:
                assert(len(sg) == 2 or len(sg) == 3)
                src = ip_address(sg[0])
                grp = ip_address(sg[1])
                if len(sg) > 2:
                    pop = int(sg[3])
                    assert(pop > 0)
                    pops[(src,grp)] = pop
                assert(grp.is_multicast)
            except Exception as e:
                logger.warning(f'{fname}:{line_num}: expected line like source_ip,group_ip[,population_count_optional]: "{line}" error: ({str(e)}')
                continue
            sgs.add((src, grp))

    sgmgr.update_sgset(sgs, pops)

def main(args_in):
    global logger, sgmgr

    parser = argparse.ArgumentParser(
        description='''This operates a CBACC filter on a joinfile, producing
an output joinfile based on the input joinfile, filtered according to the
given bandwidth limit based on CBACC-advertised stream bitrate and
priority.
''')

    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('-i', '--input-file',
        default='/etc/cbacc-in/input-control.joined-sgs',
        help='provide the full path here, the (S,G)s that are joined are dumped into this file according to polled changes in the output of cmd.  Each line is "sourceip,groupip" (no quotes)')
    parser.add_argument('-o', '--output-file',
        default='/etc/cbacc-out/output-control.joined-sgs',
        help='provide the full path here, the (S,G)s that are joined are dumped into this file according to polled changes in the output of cmd.  Each line is "sourceip,groupip" (no quotes)')
    parser.add_argument('-b', '--bandwidth', type=int,
        default=100,
        help='the maximum total bandwidth cap for joined groups, in MiBps')
    parser.add_argument('-d', '--default', type=int,
        default=None,
        help='the effective bitrate in MiBps to use for SGs without CBACC data (default is bandwidth+1, to avoid choosing them)')

    #global self_ip
    # global upstream_neighbor_ip
    args = parser.parse_args(args_in[1:])
    logger = setup_logger('cbacc-mgr', args.verbose)

    full_input_path = abspath(args.input_file)
    input_name = basename(full_input_path)
    watch_dir = dirname(full_input_path)

    if args.default is None:
        default_bw = args.bandwidth+1
    else:
        default_bw = args.default
    default_bw *= 1024*1024
    bandwidth = args.bandwidth*1024*1024

    ctx = Context()
    sgmgr = SGManager(ctx, args.output_file, default_bw, bandwidth)

    if isfile(full_input_path):
        read_joinfile(full_input_path, sgmgr)

    event_handler = PatternMatchingEventHandler(
            patterns=['*'],
            ignore_patterns=None,
            ignore_directories=True,
            case_sensitive=True)

    event_handler.on_created = on_created_handler(sgmgr, input_name)
    event_handler.on_moved = on_moved_handler(sgmgr, input_name)
    event_handler.on_modified = on_modified_handler(sgmgr, input_name)

    logger.info(f'watching {watch_dir}/{input_name}')
    observer = Observer()
    observer.schedule(event_handler, watch_dir, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    observer.stop()
    observer.join()

if __name__=="__main__":
    ret = main(sys.argv)
    exit(ret)

