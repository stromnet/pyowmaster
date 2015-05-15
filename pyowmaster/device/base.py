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
from pyownet.protocol import bytes2str, str2bytez
from time import time
import logging
from collections import namedtuple

OwIoStatistic = namedtuple('OwIoStatistic', 'id operation uncached path time')
OwIoStatistic.OP_READ=1
OwIoStatistic.OP_WRITE=2
OwIoStatistic.OP_DIR=3
OwIoStatistic.OPS = [0, 'read', 'write', 'dir']

DeviceId = namedtuple('DeviceId', 'id alias')

class OwDevice(object):
    def __init__(self, ow, id):
        self.log = logging.getLogger(type(self).__name__)
        self.id = id
        self.alias = None
        self.ow = ow

        self.path = '/%s/' % self.id
        self.pathUncached = '/uncached/%s/' % self.id
        self.simultaneous = None

    def init(self, eventDispatcher, stats):
        self.eventDispatcher = eventDispatcher
        self.stats = stats

    def config(self, config_get):
        """Configure this device from config file.
        Base impl just reads alias, first by checking device section for alias,
        secondary by checking alias section for device name"""
        self.alias = config_get(self.id, 'alias', None)
        if self.alias == None:
            self.alias = config_get('aliases', self.id, None)

        self.deviceId = DeviceId(self.id, self.alias)

    def owRead(self, subPath, uncached=False):
        if not uncached:
            path = self.path
        else:
            path = self.pathUncached

        tS = time()
        raw = self.ow.read(path + subPath)
        tE = time()

        self.storeIoStatistic(OwIoStatistic(self.id, OwIoStatistic.OP_READ, uncached, subPath, tE-tS))

        return raw

    def owWrite(self, subPath, data):
        path = self.path

        if isinstance(data, str):
            data = str2bytez(data)
        elif isinstance(data, (int, long)):
            data = str2bytez(str(data))

        tS = time()
        raw = self.ow.write(path + subPath, data)
        tE = time()

        self.storeIoStatistic(OwIoStatistic(self.id, OwIoStatistic.OP_WRITE, False, subPath, tE-tS))

        return data

    def owDir(self, subPath='', uncached=False):
        if not uncached:
            path = self.path
        else:
            path = self.pathUncached

        tS = time()
        entries = self.ow.dir(path + subPath)
        tE = time()

        self.storeIoStatistic(OwIoStatistic(self.id, OwIoStatistic.OP_DIR, uncached, subPath, tE-tS))

        return entries

    def owReadStr(self, subPath, uncached=False, strip=True):
        raw = self.owRead(subPath, uncached=uncached)

        data = bytes2str(raw)
        if strip:
            data = data.strip()

        return data

    def emitEvent(self, event, skipDeviceId=False):
        if not event.deviceId and not skipDeviceId:
            event.deviceId = self.deviceId

        self.eventDispatcher.handle_event(event)

    def storeIoStatistic(self, stats):
        # Keep last for external access
        self.lastIoStats = stats

        # Track
        self.stats.increment('ops.count_' + OwIoStatistic.OPS[stats.operation], stats.time*1000.0)
        self.stats.increment('ops.ms_' + OwIoStatistic.OPS[stats.operation], stats.time*1000.0)

        if stats.time > (1 if stats.operation != OwIoStatistic.OP_DIR else 2):
            self.log.warn("%s: %s %s took %.2fs", stats.id, OwIoStatistic.OPS[stats.operation], stats.path, stats.time)


    def on_seen(self, timestamp):
        pass

    def on_alarm(self, timestamp):
        self.log.warn("%s: Unhandled alarm" , str(self))

    def __str__(self):
        return "%s[%s]" % (self.__class__.__name__, self.deviceId)


class OwBus(OwDevice):
    """Implements a Ow Bus as a OwDevice to keep some statistics and helpers."""
    def __init__(self, ow):
       super(OwBus, self).__init__(ow, '00.000000000000')
       self.path = "/"
       self.pathUncached = "/uncached/"

    def owDirAlarm(self, uncached=False):
        return self.owDir("alarm", uncached=uncached)

    def on_seen(self, timestamp):
        raise NotImplementedError("Not supposed to call on_seen on OwBus")

    def on_alarm(self, timestamp):
        raise NotImplementedError("Not supposed to call on_alarm on OwBus")

