#!/usr/bin/env python3

# pip install requests requests_cache dnspython

import sys
import os
import json
import traceback
import requests
import requests_cache
from ipaddress import ip_address
from dns.resolver import Resolver
from itertools import groupby
import random
from requests import Request, Session
import xml.etree.ElementTree as ET
import logging
import argparse

class Context(object):
    def __init__(self):
        self.session = None

def get_logger(name):
    # python logging wtf: logger.setLevel doesn't work the obvious way:
    # https://stackoverflow.com/a/59705351/3427357 (-jake 2020-07)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    _logger = logging.getLogger(name)
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    return _logger
logger = get_logger('cbacc')

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
    servers = discover_dorms(source_ip)
    # TBD: something like asyncio.staggered_race across the server options?
    # for now just search for something satisfactory - jake 2020-07

    session = context.session
    if not session:
        session = Session()
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

            supported_cbacc_versions = set(['2019-07-31'])
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
    def __init__(self, udp_stream):
        self.port = int(udp_stream['port'])
        cb_vals = udp_stream['ietf-cbacc:cbacc']
        # default values, see:
        # https://tools.ietf.org/html/draft-ietf-mboned-cbacc-01#section-3.2
        self.max_bps = int(cb_vals['max-bits-per-second'])
        self.max_mss = int(cb_vals.get('max-mss', '1400'))
        self.rate_window = int(cb_vals.get('data-rate-window', '2000')
        self.priority = int(cb_vals.get('priority', '256')

    def __str__(self):
        return json.dumps({
            'max-bits-per-second': self.max_bps,
            'max-mss': self.max_mss,
            'data-rate-window': self.rate_window,
            'priority': self.priority,
            'port': self.port
        })

def fetch_sg_info(ctx, source, group):
    api_pre = find_base_uri(ctx, source)
    session = ctx.session
    src_ip=ip_address(source)
    group_ip=ip_address(group)
    resp = session.get(api_pre+'data/ietf-dorms:metadata/sender={src}/group={grp}/udp-stream'.format(src=src_ip.exploded, grp=group_ip.exploded))
    streams = [CbaccVals(udp_v) for udp_v in resp.json()['ietf-dorms:udp-stream']]
    return streams

def main(argv):
    argp = argparse.ArgumentParser(
        description='''discover and fetch cbacc info for an (S,G)''')
    argp.add_argument('source', help='source ip address')
    argp.add_argument('group', help='group ip address')

    args,extra=argp.parse_known_args(argv[1:])

    ctx = Context()
    ctx.session = requests.Session()
    streams = fetch_sg_info(ctx, args.source, args.group)
    print('[' + ','.join([str(s) for s in streams]) + ']')

    return 0

if __name__=="__main__":
    ret = main(sys.argv)
    exit(ret)


