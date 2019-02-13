#!/usr/bin/env python3
import sys
name=sys.argv[1]
wire=''
for dn in name.split('.'):
    if len(dn) > 0:
        wire += ('%02x' % len(dn))
        wire += (''.join('%02x'%ord(x) for x in dn))
print(len(wire)//2)
print(wire)
