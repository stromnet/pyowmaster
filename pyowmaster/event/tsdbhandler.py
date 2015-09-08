# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
#
# Copyright 2014-2015 Johan Ström
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

import socket

def create(inventory):
    tsdb = OpenTSDBEventHandler()
    return tsdb

class OpenTSDBEventHandler(ThreadedOwEventHandler):
    def __init__(self, max_queue_size=0):
        super(OpenTSDBEventHandler, self).__init__(max_queue_size)
        self.address = None
        self.socket = None

    def config(self, module_config, root_config):
        host = module_config.get('host', 'localhost')
        port = module_config.get('port', 4242)

        if self.address and \
                (self.address[0] != host or \
                 self.address[1] != port):
            self.cleanup()

        self.address = (host, port)

        # These can be overriden 
        self.metric_name = 'owfs.reading'
        self.sensor_key = 'sensor'
        self.alias_key = 'alias'
        self.type_key = 'type'
        self.channel_key = 'ch'

        # String with key=word pairs
        self.extra_tags = module_config.get('extra_tags', None)

        self.log.debug("OpenTSDB handler configured for %s", self.address)
        self.start()

    def handle_event_blocking(self, event):
        if isinstance(event, OwTemperatureEvent):
            valueFmt = "%.2f"
            type_value = "temperature"
        elif isinstance(event, OwCounterEvent):
            valueFmt = "%d"
            type_value = "counter"
        elif isinstance(event, OwStatisticsEvent):
            valueFmt = "%d"
            type_value = "stats_%s" % event.category
        else:
            return

        cmd = ("put %s %d "+valueFmt+" %s=%s") % (
                self.metric_name,
                event.timestamp,
                event.value,
                self.type_key, type_value
                )

        if event.deviceId and event.deviceId.id:
            cmd+=" %s=%s" % (self.sensor_key, event.deviceId.id)

        if self.alias_key:
            if isinstance(event, OwStatisticsEvent):
                cmd += " %s=%s" % (self.alias_key,  event.name)
            elif event.deviceId.alias:
                cmd += " %s=%s" % (self.alias_key,  event.deviceId.alias)

        if hasattr(event, 'channel'):
            cmd += " %s=%s" % (self.channel_key, event.channel)

        if self.extra_tags:
            cmd += " %s" % (self.extra_tags)

        self.send(event, cmd)

    def send(self, event, cmd, is_retry=False):
        s = self.socket
        try:
            if not s:
                s = self.socket = socket.socket()
                s.settimeout(10)
                self.log.info("Connecting TSDB %s", self.address)
                s.connect(self.address)

            #self.log.debug("TSDB: %s", cmd)
            s.sendall(cmd+"\n")
        except Exception, e:
            if is_retry:
                self.log.warn("Failed to talk to OpenTSDB: %s. Dropping event %s", e, event)
            else:
                self.log.warn("Failed to talk to OpenTSDB: %s. Reconnecting and retrying", e)

            self.cleanup()

            if not is_retry:
                self.send(event, cmd, True)

    def cleanup(self):
        if self.socket:
            self.log.info("Disconnecting TSDB")
            self.socket.shutdown(0)
            self.socket.close()
            self.socket = None

