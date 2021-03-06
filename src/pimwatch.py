#!/usr/bin/python3
import sys
import subprocess
import logging
import ipaddress
import re
import datetime
import random
import time
from enum import Enum

'''
sample from tcpdump -n -vvv pim:
05:13:35.225804 IP (tos 0x0, ttl 1, id 920, offset 0, flags [none], proto PIM (103), length 54)
    10.8.1.1 > 224.0.0.13: PIMv2, length 34
	Join / Prune, cksum 0xccc9 (correct), upstream-neighbor: 10.8.1.2
	  1 group(s), holdtime: 3m30s
	    group #1: 233.44.15.9, joined sources: 1, pruned sources: 0
	      joined source #1: 129.174.131.51(S)
'''
logger = logging.getLogger('pimwatch')
mcast_nwname = 'mcast-xmit'
amt_bridge_nwname = 'amt-bridge'
upstream_neighbor_ip = '10.10.1.1'
self_ip = '10.9.1.128'

class PimNotice(object):
    def __init__(self, hold_time):
        self.joins = []
        self.prunes = []
        self.hold_time = hold_time

    def __repr__(self):
        joins = ','.join('%s->%s' % (s,g) for s,g in self.joins)
        prunes = ','.join('%s->%s' % (s,g) for s,g in self.prunes)
        return 'Joins[%s]; Prunes[%s]' % (joins, prunes)

def pimdump_lines(ifname):
    global self_ip
    # filtering self_ip is a hack workaround because frr's mrib doesn't
    # manage the rpf propagation, so we end up sending a join and prune
    # back to the downstream port before the upstream route is added to
    # the unicast routing table in the "ip route" commands sent thru
    # vtysh.  --jake 2020-09
    cmd = ['/usr/bin/stdbuf', '-oL', '-eL', '/usr/sbin/tcpdump', '-i', ifname, '-vvv', '-n', 'pim', 'and', 'not', 'host', self_ip]
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True)
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)

def sg_joinprune_watch(ifname):
    global logger
    # TBD: notice timeout from not getting an update before holdtime
    # (e.g. neighbor powers off abruptly)
    # Join / Prune, cksum 0xccc9 (correct), upstream-neighbor: 10.8.1.2
    # 1 group(s), holdtime: 3m30s
    # group #1: 233.44.15.9, joined sources: 0, pruned sources: 1
    # joined source #1: 129.174.131.51(S)
    # pruned source #1: 129.174.131.51(S)
    jp_re = re.compile(r'\s*Join / Prune, cksum .*, upstream-neighbor: (?P<nbr>\S+)')
    summ_re = re.compile(r'\s*(?P<grp_count>\d+) group\(s\), holdtime: (?P<hold>\S+)\s*')
    grp_re = re.compile(r'\s*group #(?P<idx>\d+): (?P<grp>[^,]+), joined sources: (?P<join_cnt>\d+), pruned sources: (?P<prune_cnt>\d+)\s*')
    src_re = re.compile(r'\s*(?P<jp>joined|pruned) source #(?P<idx>\d+): (?P<src>[^(]+)\(S\)\s*')

    reset_parse_state = True
    for line in pimdump_lines(ifname):
        if reset_parse_state:
            reset_parse_state = False
            cur_nbr = None
            cur_notice = None
            cur_grp = None
            in_pkt = False
            expect_groups, expect_joins, expect_prunes = 0,0,0

        line = line.strip()
        jp = jp_re.match(line)
        if jp:
            if in_pkt or expect_groups != 0 \
                    or expect_joins != 0 or expect_prunes != 0:
                logger.warning('got new packet start without finishing last:' +
                        ('in_pkt: %s' % in_pkt) + 
                        (',expect_groups: %s' % expect_groups) +
                        (',expect_joins: %s' % expect_joins) +
                        (',expect_prunes: %s' % expect_prunes))
            in_pkt = True
            expect_groups, expect_joins, expect_prunes = 0,0,0
            cur_nbr = jp.group('nbr')
            continue

        if not in_pkt:
            logger.debug('ignoring: %s' % line)
            continue

        if expect_groups == 0:
            summ = summ_re.match(line)
            if not summ:
                logger.warning('unexpected line instead of summary: "%s"' % line)
                reset_parse_state = True
                continue
            grp_str = summ.group('grp_count')
            hold_str = summ.group('hold')
            try:
                expect_groups = int(grp_str)
            except ValueError as e:
                logger.error('%s parsing group line: "%s"' % (e, line))
                reset_parse_state = True
                continue

            if expect_groups <= 0:
                logger.warning('saw join/prune packet with groups==%d' % expect_groups)
                reset_parse_state = True
                continue

            # TBD: parse hold time: "3m30s". Be forgiving (with warnings)...
            hold_time = datetime.timedelta(seconds=210)
            cur_notice = PimNotice(hold_time)
            continue

        if not cur_notice:
            logger.error('cur_notice unset when expect_groups = %d' % expect_groups)
            reset_parse_state = True
            continue

        if expect_joins == 0 and expect_prunes == 0:
            grp = grp_re.match(line)
            if not grp:
                logger.warning('unexpected line instead of group desc: "%s"' % line)
                reset_parse_state = True
                continue

            cur_grp_str = grp.group('grp')
            join_src_str = grp.group('join_cnt')
            prune_src_str = grp.group('prune_cnt')
            try:
                cur_grp = ipaddress.ip_address(cur_grp_str)
                expect_joins = int(join_src_str)
                expect_prunes = int(prune_src_str)
            except ValueError as e:
                logger.error('%s: bad vals from line: "%s"\n  cur_grp=%s,joins=%s,prunes=%s' % (e, line, cur_grp_str, join_src_str, prune_src_str))
                reset_parse_state = True
                continue

            if expect_joins < 0 or expect_prunes < 0:
                logger.error('group desc with bad values: joins=%d, prunes=%d' % (expect_joins, expect_prunes))
                reset_parse_state = True
                continue

            if expect_joins == 0 and expect_prunes == 0:
                logger.warning('saw group with no sources joined or pruned')
            continue

        src = src_re.match(line)
        if not src:
            logger.warning('unexpected line instead of source desc: "%s"' % line)
            reset_parse_state = True
            continue

        jp_str = src.group('jp')
        src_str = src.group('src')
        try:
            src_ip = ipaddress.ip_address(src_str)
        except ValueError as e:
            logger.error('%s: bad src ip "%s" from line: "%s"' % (e, src_str, line))
            reset_parse_state = True
            continue

        if jp_str == "joined":
            if expect_joins <= 0:
                logger.error('got another join when out of expected joins in line "%s"' % line)
                reset_parse_state = True
                continue
            expect_joins -= 1
            cur_notice.joins.append((src_ip, cur_grp))
        elif jp_str == "pruned":
            if expect_prunes <= 0:
                logger.error('got another prune when out of expected prunes in line "%s"' % line)
                reset_parse_state = True
                continue
            expect_prunes -= 1
            cur_notice.prunes.append((src_ip, cur_grp))
        else:
            logger.error('unknown operation "%s" in line "%s"' % (jp_str, line))
            reset_parse_state = True
            continue

        if expect_joins == 0 and expect_prunes == 0:
            expect_groups -= 1

        if expect_groups == 0:
            logger.debug('cleanly finished join/prune packet')
            yield cur_notice
            reset_parse_state = True

class AMTRelayOption(object):
    def __init__(self, precedence, discovery_optional, typ, value):
        self.precedence = int(precedence)
        self.discovery_optional = int(discovery_optional)
        self.typ = int(typ)
        self.value = value
        if typ == 1 or typ == 2:
            self.ip = ipaddress.ip_address(value)
        else:
            self.ip = None

    def __str__(self):
        return 'prec=%d,d=%d,typ=%d,val=%s' % (self.precedence, self.discovery_optional, self.typ, self.value)

    def parse_response(out, cmd):
        '''
        example output:
$ dig +noall +answer +nocomments -t TYPE260 3.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.e.4.1.0.0.6.2.ip6.arpa
3.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.e.4.1.0.0.6.2.ip6.arpa. 7054 IN CNAME	3.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.v6.driad.akastream2.com.
3.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.v6.driad.akastream2.com. 43054 IN TYPE260 \# 22 1003047233763603616D7406616B61646E73036E6574
$ dig +noall +answer +nocomments -t TYPE260 5.185.212.23.in-addr.arpa
5.185.212.23.in-addr.arpa. 7200	IN	CNAME	5.v4.driad.akastream2.com.
5.v4.driad.akastream2.com. 43200 IN	TYPE260	\# 22 1003047235763403616D7406616B61646E73036E6574
        '''
        options = []
        for line in out.split('\n'):
            if not line:
                continue

            try:
                domain, expiry, _, typ, val = line.split(maxsplit=4)
            except ValueError as e:
                logger.warning('skipping line: error "%s" parsing dig output line "%s": failed to map into "domain, expiry, IN, type, value" (cmd=%s)' % (e, line, cmd))
                continue

            if typ == 'CNAME' or typ=='DNAME':
                # we expect some cname resolving here, see examples.
                # TBD: should we do something with these?
                continue

            if typ != 'TYPE260' and typ != 'AMTRELAY':
                logger.warning('unexpected type %s in dig output line %s, skipping (cmd=%s)' % (typ, line, cmd))
                continue

            opt = None
            if typ == 'AMTRELAY':
                precedence, discovery_optional, valtyp, valval = val.split()
                opt = AMTRelayOption(int(precedence), int(discovery_optional), int(valtyp), valval)
            else:
                opt = AMTRelayOption.parse_generic_amtrr_data(val, cmd)

            if not opt:
                continue
            logger.info('found relay option %s' % opt)
            options.append(opt)
        return options

    def parse_generic_amtrr_data(response_line, cmd):
        # example:
        # '\# 22 1003047234763403616d7406616b61646e73036e6574
        # precedence 128, dbit=0, type 3 (dns name), 'r4v4.amt.akadns.net'
        out = response_line
        out_sep = out.split(None, 2)
        if len(out_sep) != 3:
            logger.error('unexpected format of DNS response from %s: "%s"' % (cmd, out))
            return None

        head, sz_str, content = out_sep
        if head == r'\#':
            try:
                sz = int(sz_str)
            except ValueError as e:
                logger.error('failed size conversion: %s from %s, in "%s"' % (e, sz_str, out))
                return None
            try:
                bts = bytes.fromhex(content)
            except ValueError as e:
                logger.error('failed "unknown type" binary parse error: %s, from "%s", in "%s"' % (e, content, out))
                return None
            if sz != len(bts):
                logger.error('converted bytes len %d of "%s" != given len %d parsing "%s" from "%s"' % (len(bts), content, sz, out, cmd))
                return
            if sz < 3:
                logger.error('too few bytes %d parsing "%s" from "%s"' % (len(bts), out, cmd))
                return None
            precedence = bts[0]
            discovery_optional = bool(128&bts[1])
            typ = 127&bts[1]
            bin_content = bts[2:]
            try:
                if typ == 1:
                    val = ipaddress.IPv4Address(bin_content)
                elif typ == 2:
                    val = ipaddress.IPv6Address(bin_content)
                elif typ == 3:
                    idx = 0
                    name = ''
                    while idx < len(bin_content):
                        hoplen=bin_content[idx]
                        idx += 1
                        if idx + hoplen > len(bin_content) or hoplen < 0:
                            logger.error('bad wire-encoded dns name (hoplen=%d at %d with %d left, so far name="%s"):\n%s\n%s' % (hoplen, idx, len(bin_content)-idx, name, content, '  '*idx + '^'))
                            return None
                        if hoplen == 0:
                            break
                        name += bin_content[idx:idx + hoplen].decode() + '.'
                        idx += hoplen
                    val = name
                else:
                    logger.error('unknown type %d parsed from "%s" returned from "%s"' % (typ, out, cmd))
                    return None
            except ValueError as e:
                logger.error('error "%s" parsing "%s" returned from "%s"' % (e, out, cmd))
                return None
        else:
            # TBD: get an implementation with the decoded format to try this
            # logger.error('expected head to start with \\#: "%s"' % out)
            content_sep = content.split(None, 1)
            if len(content_sep) != 2:
                logger.error('failed to convert formatted content "%s" from "%s"' % (out, cmd))
                return None
            pr_str, do_str = head, sz_str
            typ_str, content_str = content_sep
            try:
                precedence = int(pr_str)
                discovery_optional = bool(int(do_str))
                typ = int(typ_str)
                if typ == 1:
                    val = ipaddress.IPv4Address(content_str)
                elif typ == 2:
                    val = ipaddress.IPv6Address(content_str)
                elif typ == 3:
                    val = content_str
                else:
                    logger.error('unknown type %d parsed from "%s" returned from "%s"' % (typ, out, cmd))
                    return None
            except ValueError as e:
                logger.error('error "%s" parsing "%s" returned from "%s"' % (e, out, cmd))
                return None

        return AMTRelayOption(precedence, discovery_optional, typ, val)

class LiveSG(object):
    def __init__(self, gw, source_ip, group_ip, expire_time):
        self.gw = gw
        self.source = ipaddress.ip_address(source_ip)
        self.group = ipaddress.ip_address(group_ip)
        if not self.group.is_multicast:
            raise ValueError('non-multicast group for %s: "%s"' % (source, group))
        self.expire_time = expire_time

    def __repr__(self):
        return '%s->%s' % (self.source, self.group)

class AMTGateway(object):
    def __init__(self, relay_ip, contname):
        self.relay_ip = ipaddress.ip_address(relay_ip)
        self.live_sgs = {} # (s,g)->LiveSG
        self.contname = contname

    def __repr__(self):
        return 'gw(%s):%d' % (self.relay_ip, len(self.live_sgs))

class ChannelManager(object):

    #dkr = '/snap/bin/docker'
    dkr = '/usr/bin/docker'

    def __init__(self, ifname):
        self.ifname = ifname
        self.live_sgs = {}  # (src_ip,grp_ip) -> LiveSG
        self.relay_ips = {} # source_ip -> relay_ip
        self.live_gateways = {} # relay_ip -> AMTGateway
                                # invariants:
                                # *self.relay_ips.get(sg.source) == gw.relay_ip
                                #  for all sg in gw.live_sgs.values()
                                # *self.live_gateways.get(gw.relay_ip)==gw
                                # for all gw in self.live_gateways.values()
        self.bad_relays = {} # ip4/ip6/hostname -> datetime when last failed
        self.badness_duration = datetime.timedelta(hours=1)

    def check_pre_existing(self):
        global logger, mcast_nwname
        '''find and stop pre-existing containers that came from pimwatch:
$ docker container ls --format={{.Names}}
pimwatch-join-23.212.185.5-232.10.2.4
pimwatch-join-23.212.185.5-232.10.2.1
pimwatch-join-23.212.185.5-232.1.1.1
pimwatch-gw-18.144.22.247
ingest-frr
        '''
        # at startup, give docker service some time to start
        retries = 0
        while True:
            cmd = [ChannelManager.dkr, 'container', 'ls', '--format={{.Names}}']
            dock_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            out, err = dock_p.communicate(cmd)
            retcode = dock_p.wait()
            if retcode == 0:
                if retries != 0:
                    logger.info('(retry successful)')
                break

            retries += 1
            if retries > 5:
                logger.error('(startup docker functionality check: retry limit exceeded): return code %d from %s, out="%s", err="%s"' % (retcode, cmd, out.strip(), err.strip()))
                return -1
            logger.info('(retry in 1s) return code %d from %s, out="%s", err="%s"' % (retcode, cmd, out.strip(), err.strip()))
            time.sleep(1)

        if err:
            logger.warning('stderr output from %s: "%s"' % (cmd, err))

        for line in out.split('\n'):
            if line.startswith('pimwatch-'):
                logger.warning('shutting down pre-existing pimwatch container %s' % line)

                cmd = [ChannelManager.dkr, 'stop', line.strip()]
                dock_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                out, err = dock_p.communicate(cmd)
                retcode = dock_p.wait()
                if retcode != 0:
                    logger.error('shutdown of pre-existing pimwatch container %s failed, aborting' % line)
                    logger.error('return code %d from %s, out="%s", err="%s"' % (retcode, cmd, out, err))
                    return -1

                if err:
                    logger.warning('stderr output from %s: "%s"' % (cmd, err))

        cmd = [ChannelManager.dkr, 'network', 'inspect', mcast_nwname]
        dock_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out, err = dock_p.communicate(cmd)
        retcode = dock_p.wait()
        if retcode != 0:
            logger.error('no %s network detected, aborting' % mcast_nwname)

            '''
            cmd = [ChannelManager.dkr, 'network', 'create', '--driver', 'macvlan', '--subnet=10.9.1.0/24', '--ip-range=10.9.1.64/26', '--gateway=10.9.1.1', '-o', 'parent=irf0', mcast_nwname]
            dock_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            out, err = dock_p.communicate(cmd)
            retcode = dock_p.wait()
            if retcode != 0:
                logger.warning('return code %d from %s, out="%s", err="%s"' % (retcode, cmd, out, err))
                return
            '''
            return -1
        return 0

    def pick_relay_for_source(self, options):
        if not options:
            return None
        if len(options) < 1:
            return None
        worse_options = sorted(options, key=lambda x: x.precedence)
        options = []

        now = None
        while True:
            if len(options) < 1:
                if len(worse_options) < 1:
                    return None
                low_p = worse_options[0].precedence
                new_worse = []
                for opt in worse_options:
                    lst = options if opt.precedence == low_p else new_worse
                    lst.append(opt)
                worse_options = new_worse
            assert(len(options) > 0)
            idx = random.randrange(len(options))
            logger.info('randomly chose idx %d of %d relay options' % (idx, len(options)))
            opt = options[idx]
            bad_time = self.bad_relays.get(opt.value)
            if not bad_time:
                return opt

            if not now:
                now = datetime.datetime.now()

            if now - bad_time >= self.badness_duration:
                logger.warning('relay %s previously failed at %s, retrying since after %s' % (opt.value, bad_time, self.badness_duration))
                del(self.bad_relays[opt.value])
                return opt

            logger.warning('rejected relay %s that last failed at %s (< %s)' % (opt.value, bad_time, self.badness_duration))
            del(options[idx])

        return None

    def find_relay_options_for_source(self, src_ip):
        name = src_ip.reverse_pointer
        cmd = ['/usr/bin/dig', '+noall', '+answer', '+nocomments', '-t', 'TYPE260', name]
        dig_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out, err = dig_p.communicate(cmd)
        retcode = dig_p.wait()
        if retcode != 0:
            logger.warning('return code %d from %s, out="%s", err="%s"' % (retcode, cmd, out, err))
            return None

        if err:
            logger.warning('stderr output from %s: "%s"' % (cmd, err))

        return AMTRelayOption.parse_response(out, cmd)

    def find_relay(self, src_ip):
        options = self.find_relay_options_for_source(src_ip)
        opt = None
        while True:
            if opt:
                # last try failed ip lookup. remove it and try again
                self.bad_relays[opt.value] = datetime.datetime.now()
                options = [o for o in options if opt.value != o.value]
            opt = self.pick_relay_for_source(options)
            if not opt:
                return None
            if opt.ip:
                return opt
            assert(opt.typ == 3)
            cmd = ['/usr/bin/dig', '+short', opt.value]
            dig_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            out, err = dig_p.communicate(cmd)
            retcode = dig_p.wait()
            if retcode != 0:
                logger.error('return code %s from %s, out="%s", err="%s", rejecting relay %s' % (retcode, cmd, out, err, opt.value))
                continue
            if err:
                logger.warning('stderr output from %s: "%s"' % (cmd, err))

            out = out.strip()
            if len(out) == 0:
                logger.error('no ips from "%s", rejecting relay %s' % (cmd, opt.value))
                continue
            out_lines = out.split('\n')
            out_line = out_lines[random.randrange(len(out_lines))]
            try:
                out_ip = ipaddress.ip_address(out_line)
            except ValueError as e:
                logger.error('bad ip "%s" from "%s": %s, rejecting relay %s' % (out_line, cmd, e, opt.value))
                continue
            opt.ip = out_ip
            return opt

    def launch_gateway(self, relay_ip):
        global logger, mcast_nwname, amt_bridge_nwname
        logger.info('launching gateway to relay %s' % (relay_ip,))

        nwname = mcast_nwname
        contname = 'pimwatch-gw-%s' % (relay_ip.exploded)
        imagename = 'grumpyoldtroll/amtgw:latest'
        cmd = [ChannelManager.dkr, 'create', '--rm', '--name', contname, '--privileged', '--network', amt_bridge_nwname, imagename, str(relay_ip)]
        logger.info('running: %s' % (' '.join(cmd)))
        launch_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out, err = launch_p.communicate(cmd)
        retcode = launch_p.wait()
        if retcode != 0:
            logger.error('return code %s from %s, out="%s", err="%s", failed gw launch' % (retcode, cmd, out, err))
            return None

        cmd = [ChannelManager.dkr, 'network', 'connect', nwname, contname]
        logger.info('running: %s' % (' '.join(cmd)))
        connect_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out, err = connect_p.communicate(cmd)
        retcode = connect_p.wait()
        if retcode != 0:
            logger.error('return code %s from %s, out="%s", err="%s", failed gw connect' % (retcode, cmd, out, err))
            cmd = [ChannelManager.dkr, 'container', 'stop', contname]
            stopret = subprocess.run(cmd)
            logger.warning('stopped container: %s' % (stopret))
            return None

        time.sleep(1)
        cmd = [ChannelManager.dkr, 'start', contname]
        logger.info('running: %s' % (' '.join(cmd)))
        start_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out, err = start_p.communicate(cmd)
        retcode = start_p.wait()
        if retcode != 0:
            logger.error('return code %s from %s, out="%s", err="%s", failed gw start' % (retcode, cmd, out, err))
            cmd = [ChannelManager.dkr, 'container', 'stop', contname]
            stopret = subprocess.run(cmd)
            logger.warning('stopped container: %s' % (stopret))
            return None

        gw = AMTGateway(relay_ip, contname)
        self.live_gateways[relay_ip] = gw

        return gw


    def launch_sg_join(self, sg, gw, expire_time):
        global logger
        source, group = sg
        assert(not sg in gw.live_sgs)
        assert(not sg in self.live_sgs)

        logger.info('launching join for %s' % (sg,))

        source = ipaddress.ip_address(source)
        group = ipaddress.ip_address(group)

        cmd = ['/usr/bin/vtysh']
        in_stdio = "config term\ninterface eth1\nip igmp join %s %s\nexit\nexit\n" % (group, source)
        logger.info('running %s <<EOF\n%sEOF' % (' '.join(cmd), in_stdio))
        launch_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, universal_newlines=True)
        out, err = launch_p.communicate(input=in_stdio)

        '''
        # the old way was to launch another docker container just to
        # run iperf-ssm.  The new way is the above attempt to do an igmp
        # join inside vtysh
        nwname = mcast_nwname
        contname = 'pimwatch-join-%s-%s' % (source.exploded, group.exploded)
        imagename = 'grumpyoldtroll/iperf-ssm:latest'
        # TBD: support v6--iperf command is different
        # TBD: iperf-ssm is overkill and cruelly doomed to wait (or worse,
        # catch packets if they go to the right port). all i need is a
        # program that stays joined in the gateway's data network.
        cmd = [ChannelManager.dkr, 'run', '-d', '--network', nwname, '--rm', '--name', contname, imagename, '--server', '--udp', '--bind', str(group), '--source', str(source), '--interval', '1', '--len', '1500', '--interface', 'eth0']
        launch_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out, err = launch_p.communicate(cmd)
        '''

        retcode = launch_p.wait()
        if retcode != 0:
            logger.error('return code %s from %s, out="%s", err="%s", failed joiner launch' % (retcode, cmd, out, err))
            return None
        live_sg = LiveSG(gw, source, group, expire_time)
        gw.live_sgs[sg] = live_sg
        self.live_sgs[sg] = live_sg
        return live_sg

    def stop_gw(self, gw):
        global logger

        logger.info('stopping gw %s' % gw)
        cmd = [ChannelManager.dkr, 'container', 'stop', gw.contname]
        stopret = subprocess.run(cmd)
        logger.info('stopped container: %s' % (stopret))

        del(self.live_gateways[gw.relay_ip])

    def stop_sg(self, sg):
        global logger, upstream_neighbor_ip

        logger.info('stopping sg %s' % (sg,))

        source, group = sg.source, sg.group

        source = ipaddress.ip_address(source)
        group = ipaddress.ip_address(group)
        cmd = ['/usr/bin/vtysh']
        in_stdio = "config term\ninterface eth1\nno ip igmp join %s %s\nexit\nexit\n" % (group, source)
        logger.info('running %s <<EOF\n%sEOF' % (' '.join(cmd), in_stdio))
        launch_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, universal_newlines=True)
        out, err = launch_p.communicate(input=in_stdio)

        '''
        cmd = [ChannelManager.dkr, 'container', 'stop', sg.contname]
        stopret = subprocess.run(cmd)
        logger.info('stopped container: %s' % (stopret))
        '''

        gw = sg.gw
        ip_sg = (sg.source, sg.group)
        if ip_sg not in self.live_sgs:
            logger.error('internal error: %s not in self.live_sgs in stop_sg' % (ip_sg,))
        else:
            del(self.live_sgs[ip_sg])

        if ip_sg not in gw.live_sgs:
            logger.error('internal error: %s not in gw.live_sgs in stop_sg' % (ip_sg,))
        else:
            logger.info('removing %s from gw %s' % (sg, gw))
            del(gw.live_sgs[ip_sg])
            other_sg = None
            for other in gw.live_sgs.values():
                if other.source == sg.source:
                    other_sg = other
                    break
            if other_sg:
                logger.info('source %s stays alive for other sg %s' % (sg.source, other_sg))
            else:
                if sg.source in self.relay_ips:
                    logger.info('source %s removed from relay_ips (%s)' % (sg.source, self.relay_ips[sg.source]))
                    del(self.relay_ips[sg.source])

                    logger.info('removing rpf route for %s' % (sg.source,))
                    cmd = ['/usr/bin/vtysh']
                    in_stdio = "config term\nno ip route %s/32 %s\nexit\n" % (sg.source, upstream_neighbor_ip)
                    launch_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, universal_newlines=True)
                    out, err = launch_p.communicate(input=in_stdio)
                    retcode = launch_p.wait()
                    if retcode != 0:
                        logger.error('return code %s from %s removing route to source failed, out="%s", err="%s", failed joiner launch' % (retcode, cmd, out, err))
                else:
                    logger.error('internal error: source %s not in relay_ips during stop_sg(%s)' % (sg.source, sg))
            if len(gw.live_sgs) == 0:
                logger.info('shutting down gw %s with no more sgs' % (gw))
                self.stop_gw(gw)
            else:
                logger.info('gw stays alive for %s' % (gw.live_sgs))

    def add_or_refresh_sg(self, sg, notice_time, hold_time):
        global upstream_neighbor_ip

        # TBD: grace period if we took too long, maybe not just notice+hold
        expire_time = notice_time + hold_time
        live_sg = self.live_sgs.get(sg)
        if live_sg:
            logger.info('live sg refreshed: %s' % (live_sg))
            live_sg.expire_time = expire_time
            return

        src_ip, grp_ip = sg
        logger.info('adding new sg: %s->%s' % (src_ip, grp_ip))

        relay_ip = self.relay_ips.get(src_ip)
        relay_opt = None
        gw = None
        while not live_sg:
            if not relay_ip:
                logger.info('finding relay ip for %s' % src_ip)
                relay_opt = self.find_relay(src_ip)
                if not relay_opt:
                    logger.error('failed to add relay for %s' % (sg,))
                    return
                if not relay_opt.ip:
                    logger.error('internal error: no ip for relay %s, for %s' % (relay_opt.value, sg))
                    self.bad_relays[relay_opt.value] = datetime.datetime.now()
                    continue
                relay_ip = relay_opt.ip
                self.relay_ips[src_ip] = relay_ip
                logger.info('found relay ip %s for src %s' % (relay_ip, src_ip))

                logger.info('adding rpf route for %s' % (src_ip,))
                cmd = ['/usr/bin/vtysh']
                in_stdio = "config term\nip route %s/32 %s\nexit\n" % (src_ip, upstream_neighbor_ip)
                launch_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, universal_newlines=True)
                out, err = launch_p.communicate(input=in_stdio)
                retcode = launch_p.wait()
                if retcode != 0:
                    logger.error('return code %s from %s removing route to source failed, out="%s", err="%s", failed joiner launch' % (retcode, cmd, out, err))

            gw = self.live_gateways.get(relay_ip)
            if not gw:
                gw = self.launch_gateway(relay_ip)
                if not gw:
                    logger.error('failed to add live gateway for relay %s' % (relay_ip))
                    del(self.relay_ips[src_ip])
                    if not relay_opt:
                        logger.error('internal error: unexpectedly have a relay_ip %s for non-live gw without having just made it' % (relay_ip))
                        relay_ip = None
                        continue
                    self.bad_relays[relay_opt.value] = datetime.datetime.now()
                    relay_ip = None
                    continue

            if sg in gw.live_sgs:
                logger.error('internal error: sg %s in gateway %s but not channelmgr, added to list' % (sg, gw))
                live_sg = gw.live_sgs[sg]
                self.live_sgs[sg] = live_sg
                continue

            live_sg = self.launch_sg_join(sg, gw, expire_time)
            if not live_sg:
                logger.error('failed to launch sg %s' % (sg,))
                if len(gw.live_sgs) == 0:
                    logger.info('shutting down empty gateway')
                    self.stop_gw(gw)
                    return

    def remove_sg(self, sg):
        live_sg = self.live_sgs.get(sg)
        if not live_sg:
            logger.info('ignored pruning non-live sg: %s' % (sg,))
            return
        logger.info('removing live sg: %s' % (live_sg))
        self.stop_sg(live_sg)

def main(args):
    global logger, upstream_neighbor_ip, self_ip

    logging.basicConfig(format='pimwatch %(asctime)-15s:%(levelname)s %(message)s')

    if False: # TBD: cmd line flag?  running from service under journalctl this isn't needed but standalone it is. --jake 2020-09
        handler = RotatingFileHandler("pimwatch.log", maxBytes=10000000, backupCount=5)
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)

    ifname = args[1]
    dnsserver = None

    self_ip = args[2]

    upstream_neighbor_ip = args[3]

    logger.info('started pimwatch, ifname=%s, upstream neighbor=%s, self_ip=%s' % (ifname, upstream_neighbor_ip, self_ip))
    channels = ChannelManager(ifname)
    ret = channels.check_pre_existing()
    if ret != 0:
        logger.error('prequisites check failed')
        exit(ret)

    for sgpkt in sg_joinprune_watch(ifname):
        logger.debug('saw sg notice: "%s"', sgpkt)
        notice_time = datetime.datetime.now()
        for sg in sgpkt.joins:
            channels.add_or_refresh_sg(sg, notice_time, sgpkt.hold_time)
        for sg in sgpkt.prunes:
            channels.remove_sg(sg)

    return 0

if __name__=="__main__":
    retval = main(sys.argv)
    sys.exit(retval)

