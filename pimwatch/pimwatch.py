#!/usr/bin/python3
import sys
import subprocess
import logging
import ipaddress
import re
import datetime
import random
import time
import argparse
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
#logger = logging.getLogger('pim2joinfile')
logger = None
upstream_interface = None
downstream_interface = None
joinfile = None

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
    cmd = ['/usr/bin/stdbuf', '-oL', '-eL', '/usr/bin/tcpdump', '-i', ifname, '-vvv', '-n', '-Qin', 'pim']
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True)
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)

def sg_joinprune_watch(ifname):
    '''
    watches ifname with tcpdump, yields PimNotice objects.
    '''

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
            #logger.debug('ignoring: %s' % line)
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

class LiveSG(object):
    def __init__(self, source_ip, group_ip, expire_time):
        self.source = ipaddress.ip_address(source_ip)
        self.group = ipaddress.ip_address(group_ip)
        if not self.group.is_multicast:
            raise ValueError('non-multicast group for %s: "%s"' % (source, group))
        self.expire_time = expire_time

    def __repr__(self):
        return '%s->%s' % (self.source, self.group)

class ChannelManager(object):

    #dkr = '/snap/bin/docker'
    dkr = '/usr/bin/docker'

    def __init__(self, upstream, downstream):
        self.upstream = upstream
        self.downstream = downstream
        self.live_sgs = {}  # (src_ip,grp_ip) -> LiveSG

    def launch_sg_join(self, sg, expire_time):
        global logger
        source, group = sg
        assert(not sg in self.live_sgs)

        logger.info('launching join for %s' % (sg,))

        source = ipaddress.ip_address(source)
        group = ipaddress.ip_address(group)

        # the current way to do it is to add an smcroutectl route from the
        # upstream interface to the downstream interface for the group.
        # (the upstream join is done by the driad-ingest)
        # additionally, change the joinfile so that the upstream
        # driad-ingest (or cbacc) will handle it
        live_sg = LiveSG(source, group, expire_time)
        self.live_sgs[sg] = live_sg
        joinfile_out = '\n'.join([f'{s},{g}' for (s,g) in self.live_sgs.keys()])
        with open(joinfile, 'w') as f:
            print(joinfile_out, file=f)

        return live_sg

        '''
        # the next oldest way to do it was to tell frr to do the igmp join and rely on frr's pim forwarding
        cmd = ['/usr/bin/vtysh']
        in_stdio = "config term\ninterface eth1\nip igmp join %s %s\nexit\nexit\n" % (group, source)
        logger.info('running %s <<EOF\n%sEOF' % (' '.join(cmd), in_stdio))
        launch_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, universal_newlines=True)
        out, err = launch_p.communicate(input=in_stdio)
        '''

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

        retcode = launch_p.wait()
        if retcode != 0:
            logger.error('return code %s from %s, out="%s", err="%s", failed joiner launch' % (retcode, cmd, out, err))
            return None
        live_sg = LiveSG(source, group, expire_time)
        self.live_sgs[sg] = live_sg
        return live_sg
        '''

    def stop_sg(self, sg):
        global logger, joinfile

        logger.info('stopping sg %s' % (sg,))

        source, group = sg.source, sg.group
        ip_sg = (sg.source, sg.group)
        if ip_sg not in self.live_sgs:
            logger.error('internal error: %s not in self.live_sgs in stop_sg' % (ip_sg,))
        else:
            del(self.live_sgs[ip_sg])

        joinfile_out = '\n'.join([f'{s},{g}' for (s,g) in self.live_sgs.keys()])
        with open(joinfile, 'w') as f:
            print(joinfile_out, file=f)


        '''
        source = ipaddress.ip_address(source)
        group = ipaddress.ip_address(group)
        cmd = ['/usr/bin/vtysh']
        in_stdio = "config term\ninterface eth1\nno ip igmp join %s %s\nexit\nexit\n" % (group, source)
        logger.info('running %s <<EOF\n%sEOF' % (' '.join(cmd), in_stdio))
        launch_p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, universal_newlines=True)
        out, err = launch_p.communicate(input=in_stdio)
        '''

        '''
        cmd = [ChannelManager.dkr, 'container', 'stop', sg.contname]
        stopret = subprocess.run(cmd)
        logger.info('stopped container: %s' % (stopret))

        ip_sg = (sg.source, sg.group)
        if ip_sg not in self.live_sgs:
            logger.error('internal error: %s not in self.live_sgs in stop_sg' % (ip_sg,))
        else:
            del(self.live_sgs[ip_sg])
        '''

    def add_or_refresh_sg(self, sg, notice_time, hold_time):
        # TBD: grace period if we took too long, maybe not just notice+hold
        expire_time = notice_time + hold_time
        live_sg = self.live_sgs.get(sg)
        if live_sg:
            logger.info('live sg refreshed: %s' % (live_sg))
            live_sg.expire_time = expire_time
            return

        src_ip, grp_ip = sg
        logger.info('adding new sg: %s->%s' % (src_ip, grp_ip))

        while not live_sg:
            live_sg = self.launch_sg_join(sg, expire_time)
            if not live_sg:
                logger.error('failed to launch sg %s' % (sg,))

    def remove_sg(self, sg):
        live_sg = self.live_sgs.get(sg)
        if not live_sg:
            logger.info('ignored pruning non-live sg: %s' % (sg,))
            return
        logger.info('removing live sg: %s' % (live_sg))
        self.stop_sg(live_sg)

def get_logger(name, verbosity=0):
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

def main(args_in):
    global logger, joinfile, upstream_interface, downstream_interface

    parser = argparse.ArgumentParser(
        description='This is an implementation of an egress node in draft-jholland-mboned-mnat.')

    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('-u', '--upstream', required=True,
            help='this is the upstream interface, for routes to be added based on downstream join/prunes')
    parser.add_argument('-d', '--downstream', required=True,
            help='this is the downstream interface with hopefully a connection to a pim network, monitored for joins and prunes')
    parser.add_argument('-j', '--joinfile', required=True,
        help='Name of the file inside the container where (S,G)s will be updated (needs absolute path within the container)')

    args = parser.parse_args(args_in[1:])

    logger = get_logger('pimwatch', args.verbose)

    if False: # TBD: cmd line flag?  running from service under journalctl this isn't needed but standalone it is. --jake 2020-09
        handler = RotatingFileHandler("pimwatch.log", maxBytes=10000000, backupCount=5)
        logger.addHandler(handler)

    joinfile = args.joinfile
    upstream_interface = args.upstream
    downstream_interface = args.downstream

    logger.info(f'started pimwatch, downstream={downstream_interface} upstream={upstream_interface}')
    channels = ChannelManager(upstream_interface, downstream_interface)
    '''
    if ret != 0:
        logger.error('prequisites check failed')
        exit(ret)
    '''
    with open(joinfile, 'w') as f:
        print('', file=f)

    for sgpkt in sg_joinprune_watch(downstream_interface):
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

