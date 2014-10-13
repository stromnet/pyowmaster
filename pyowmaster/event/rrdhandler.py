# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
#
# Copyright 2014 Johan Ström
#
# This python package is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
from handler import ThreadedOwEventHandler
from events import *

import rrdtool
import os, time
from os.path import abspath, exists, isdir

def create(config_get, inventory):
    return RRDOwEventHandler(config_get('rrdhandler', 'rrdpath', os.getcwd()))

class RRDOwEventHandler(ThreadedOwEventHandler):
    def __init__(self, rrdpath, max_queue_size=0):
        super(RRDOwEventHandler, self).__init__(max_queue_size)
        rrdpath = abspath(rrdpath) + os.sep
        if exists(rrdpath):
            if not isdir(rrdpath):
                raise Exception("Specified RRD path %s exist but is not a directory" % rrdpath)

            # Ensure we can write
            fn = "%s%s-%d" % (rrdpath, ".rrdOwEventHandler-write-test-tmp", time.time())
            try:
                fd = open(fn, 'w+')
                os.unlink(fn)
            except IOError, e:
                if e.errno == 13:
                    raise Exception("Cannot write to specified RRD path %s" % rrdpath)

        else:
            os.makedirs(rrdpath)

        self.rrdpath = rrdpath

        self.log.debug("RRD handler ready with path %s", rrdpath)
        self.start()

    def handle_event_blocking(self, event):
        if isinstance(event, OwTemperatureEvent):
            rrdfile = "%s%s.rrd" % (self.rrdpath, event.deviceId.id)
            dsType = "GAUGE"
        elif isinstance(event, OwCounterEvent):
            rrdfile = "%s%s-%s.rrd" % (self.rrdpath, event.deviceId.id, event.channel)
            dsType = "COUNTER"
        elif isinstance(event, OwStatisticsEvent):
            rrdfile = "%s%s-%s.rrd" % (self.rrdpath, event.category, event.deviceId.alias)
            dsType = "COUNTER"
        else:
            return

        if not exists(rrdfile):
            self.create(rrdfile, dsType)

        #self.log.debug("Updating %s", rrdfile)
        if dsType == "GAUGE":
            rrdtool.update(rrdfile, "%d:%.2f" % (event.timestamp, event.value)) 
        elif dsType == "COUNTER":
            rrdtool.update(rrdfile, "%d:%d" % (event.timestamp, event.value)) 

    def create(self, rrdfile, dsType):
        """Create a new RRD file. TODO not hardcode..."""
        self.log.info("Creating %s", rrdfile)
        rrdtool.create(rrdfile,
                '-s', '60', \
                'DS:value:%s:120:U:U' % dsType, \
                'RRA:AVERAGE:0.5:1:1440', \
                'RRA:AVERAGE:0.5:5:2016', \
                'RRA:AVERAGE:0.5:15:2976', \
                'RRA:AVERAGE:0.5:60:4464', \
                'RRA:AVERAGE:0.5:360:1460', \
                'RRA:MIN:0.5:1:1440', \
                'RRA:MIN:0.5:5:2016', \
                'RRA:MIN:0.5:15:2976', \
                'RRA:MIN:0.5:60:4464', \
                'RRA:MIN:0.5:360:1460', \
                'RRA:MAX:0.5:1:1440', \
                'RRA:MAX:0.5:5:2016', \
                'RRA:MAX:0.5:15:2976', \
                'RRA:MAX:0.5:60:4464')
        
