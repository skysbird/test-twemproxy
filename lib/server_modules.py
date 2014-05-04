#!/usr/bin/env python
#coding: utf-8
#file   : server_modules.py
#author : ning
#date   : 2014-02-24 13:00:28


import os
import sys

from utils import *
import conf

class Base:
    '''
    the sub class should implement: _alive, _pre_deploy, status, and init self.args
    '''
    def __init__(self, name, host, port, path):
        self.args = {
            'name'      : name,
            'host'      : host,
            'port'      : port,
            'path'      : path,

            'startcmd'  : '',     #startcmd and runcmd will used to generate the control script
            'runcmd'    : '',     #process name you see in `ps -aux`, we use this to generate stop cmd
            'logfile'   : '',
        }

    def __str__(self):
        return TT('[$name:$host:$port]', self.args)

    def deploy(self):
        logging.info('deploy %s' % self)
        self._run(TT('mkdir -p $path/bin && mkdir -p $path/conf && mkdir -p $path/log && mkdir -p $path/data ', self.args))

        self._pre_deploy()
        self._gen_control_script()

    def _gen_control_script(self):
        content = file(os.path.join(WORKDIR, 'conf/control.sh')).read()
        content = TT(content, self.args)

        control_filename = TT('${path}/${name}_control', self.args)

        fout = open(control_filename, 'w+')
        fout.write(content)
        fout.close()
        os.chmod(control_filename, 0755)

    def start(self):
        if self._alive():
            logging.warn('%s already running' %(self) )
            return

        logging.debug('starting %s' % self)
        t1 = time.time()
        sleeptime = .1

        cmd = TT("cd $path && ./${name}_control start", self.args)
        self._run(cmd)

        while not self._alive():
            lets_sleep(sleeptime)
            if sleeptime < 5:
                sleeptime *= 2
            else:
                sleeptime = 5
                logging.warn('%s still not alive' % self)

        t2 = time.time()
        logging.info('%s start ok in %.2f seconds' %(self, t2-t1) )

    def stop(self):
        if not self._alive():
            logging.warn('%s already stop' %(self) )
            return

        cmd = TT("cd $path && ./${name}_control stop", self.args)
        self._run(cmd)

        t1 = time.time()
        while self._alive():
            lets_sleep()
        t2 = time.time()
        logging.info('%s stop ok in %.2f seconds' %(self, t2-t1) )

    def status(self):
        logging.warn("status: not implement")

    def log(self):
        cmd = TT('tail $logfile', self.args)
        logging.info('log of %s' % self)
        print self._run(cmd)

    def _alive(self):
        logging.warn("_alive: not implement")

    def _run(self, raw_cmd):
        ret = system(raw_cmd, logging.debug)
        logging.debug('return : [%d] [%s] ' % (len(ret), shorten(ret)) )
        return ret


class RedisServer(Base):
    def __init__(self, host, port, path, cluster_name, server_name):
        Base.__init__(self, 'redis', host, port, path)

        self.args['startcmd']     = TT('bin/redis-server conf/redis.conf', self.args)
        self.args['runcmd']       = TT('redis-server \*:$port', self.args)
        self.args['conf']         = TT('$path/conf/redis.conf', self.args)
        self.args['pidfile']      = TT('$path/log/redis.pid', self.args)
        self.args['logfile']      = TT('$path/log/redis.log', self.args)
        self.args['dir']          = TT('$path/data', self.args)
        self.args['REDIS_CLI']    = conf.BINARYS['REDIS_CLI']

        self.args['cluster_name'] = cluster_name
        self.args['server_name']  = server_name

    def _info_dict(self):
        cmd = TT('$REDIS_CLI -h $host -p $port INFO', self.args)
        info = self._run(cmd)

        info = [line.split(':', 1) for line in info.split('\r\n') if not line.startswith('#')]
        info = [i for i in info if len(i)>1]
        return defaultdict(str, info) #this is a defaultdict, be Notice

    def _ping(self):
        cmd = TT('$REDIS_CLI -h $host -p $port PING', self.args)
        return self._run(cmd)

    def _alive(self):
        return strstr(self._ping(), 'PONG')

    def _gen_conf(self):

        content = file(os.path.join(WORKDIR, 'conf/redis.conf')).read()
        #content = file('conf/redis.conf').read()
        return TT(content, self.args)

    def _pre_deploy(self):
        self.args['BINS'] = conf.BINARYS['REDIS_SERVER_BINS']
        self._run(TT('cp $BINS $path/bin/', self.args))

        fout = open(TT('$path/conf/redis.conf', self.args), 'w+')
        fout.write(self._gen_conf())
        fout.close()

    def status(self):
        uptime = self._info_dict()['uptime_in_seconds']
        if uptime:
            logging.info('%s uptime %s seconds' % (self, uptime))
        else:
            logging.error('%s is down' % self)

    def isslaveof(self, master_host, master_port):
        info = self._info_dict()
        if info['master_host'] == master_host and int(info['master_port']) == master_port:
            logging.debug('already slave of %s:%s' % (master_host, master_port))
            return True

    def slaveof(self, master_host, master_port):
        cmd = 'SLAVEOF %s %s' % (master_host, master_port)
        return self.rediscmd(cmd)

    def rediscmd(self, cmd):
        args = copy.deepcopy(self.args)
        args['cmd'] = cmd
        cmd = TT('$REDIS_CLI -h $host -p $port $cmd', args)
        logging.info('%s %s' % (self, cmd))
        print self._run(cmd)


class NutCracker(Base):
    def __init__(self, host, port, path, cluster_name, masters, mbuf=512, verbose=4):
        Base.__init__(self, 'nutcracker', host, port, path)

        self.masters = masters

        self.args['mbuf']        = mbuf
        self.args['verbose']     = verbose
        self.args['conf']        = TT('$path/conf/nutcracker.conf', self.args)
        self.args['pidfile']     = TT('$path/log/nutcracker.pid', self.args)
        self.args['logfile']     = TT('$path/log/nutcracker.log', self.args)
        self.args['status_port'] = self.args['port'] + 1000

        self.args['startcmd']    = TT('bin/nutcracker -d -c $conf -o $logfile -p $pidfile -s $status_port -v $verbose -m $mbuf', self.args)
        self.args['runcmd']    = TT('bin/nutcracker -d -c $conf -o $logfile -p $pidfile -s $status_port', self.args)

        self.args['cluster_name']= cluster_name

    def _alive(self):
        return self._info_dict()

    def _gen_conf_section(self):
        template = '    - $host:$port:1 $server_name'
        cfg = '\n'.join([TT(template, master.args) for master in self.masters])
        return cfg

    def _gen_conf(self):
        content = '''
$cluster_name:
  listen: 0.0.0.0:$port
  hash: fnv1a_64
  distribution: modula
  preconnect: true
  auto_eject_hosts: false
  redis: true
  backlog: 512
  timeout: 400
  client_connections: 0
  server_connections: 1
  server_retry_timeout: 2000
  server_failure_limit: 2
  servers:
'''
        content = TT(content, self.args)
        return content + self._gen_conf_section()

    def _pre_deploy(self):
        self.args['BINS'] = conf.BINARYS['NUTCRACKER_BINS']
        self._run(TT('cp $BINS $path/bin/', self.args))

        fout = open(TT('$path/conf/nutcracker.conf', self.args), 'w+')
        fout.write(self._gen_conf())
        fout.close()

    def _info_dict(self):
        try:
            ret = telnetlib.Telnet(self.args['host'], self.args['status_port']).read_all()
            return json_decode(ret)
        except Exception, e:
            logging.debug('--- can not get _info_dict of nutcracker, [Exception: %s]' % (e, ))
            return None

    def reconfig(self, masters):
        self.masters = masters
        self.stop()
        self.deploy()
        self.start()
        logging.info('proxy %s:%s is updated' % (self.args['host'], self.args['port']))

    def host(self):
        return self.args['host']
    def port(self):
        return self.args['port']


# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4


