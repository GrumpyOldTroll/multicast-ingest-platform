#!/bin/env python3

import ipaddress
import argparse
import sys

'''
Generates zone file entries for an AMT relay, to be put in the reverse
zone for the sender's source IP.
'''

def translate_domain(domain):
    '''domain name input, wire format bytes returned'''
    content = b''
    for dn in domain.split('.'):
        if len(dn) > 63:
            raise ValueError('domain element too long')
        content += bytes([len(dn)])
        content += bytes([ord(x) for x in dn])
    if len(dn) != 0:
        content += bytes([0])
    if len(content) > 255:
        raise ValueError('domain name too long')
    return content

def main(args_in):
    parser = argparse.ArgumentParser(
            description='''
Build a zone file entry for an AMT relay or set of relays.  See
RFC 8777 (including errata).''')
    parser.add_argument('-r', '--relay', help='IP address or domain name of the relay (required)', required=True)
    parser.add_argument('-p', '--precedence', help='Precedence value (lower number = more preferred', default=16, type=int)
    parser.add_argument('-d', '--discovery-optional', help='D-bit (whether the AMT discovery handshake can be skipped)', choices=[0,1], default=0)

    args=parser.parse_args(args_in[1:])

    relay = args.relay
    relay_type=3
    content = None
    try:
        relay_ip = ipaddress.ip_address(relay)
        if relay_ip.version == 4:
            relay_type=1
            content = relay_ip.packed
            content_str = relay_ip.compressed
        elif relay_ip.version == 6:
            relay_type=2
            content = relay_ip.packed
            content_str = relay_ip.compressed
    except ValueError as ve:
        relay_type=3
        if not relay.endswith('.'):
            relay = relay + '.'
        content = translate_domain(relay)
        content_str = relay

    print('; IN AMTRELAY %d %d %d %s' % (args.precedence, args.discovery_optional, relay_type, content_str))
    print('IN TYPE260 \\# ( %d %02x %02x %s )' % (len(content) + 2, args.precedence, args.discovery_optional*128 + relay_type, content.hex()))

    return 0

if __name__=="__main__":
    ret = main(sys.argv)
    exit(ret)

