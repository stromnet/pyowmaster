# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
from pyownet.protocol import bytes2str, str2bytez
from time import time
import logging
from collections import namedtuple

OwIoStatistic = namedtuple('OwIoStatistic', 'id operation uncached time')
OwIoStatistic.OP_READ=1
OwIoStatistic.OP_WRITE=2
OwIoStatistic.OP_DIR=3

DeviceId = namedtuple('DeviceId', 'id alias')

class OwEventBase(object):
    """Base object for any events sent emitted from
    1-Wire devices as result of alarms or regular polling"""
    def __init__(self):
        self.id = None

    def __str__(self):
        return "OwEvent[%s, unknown]" % (self.id)

class OwDevice(object):
    def __init__(self, ow, id):
        self.log = logging.getLogger(type(self).__name__)
        self.id = id
        self.alias = None
        self.ow = ow

        self.path = '/%s/' % self.id
        self.pathUncached = '/uncached/%s/' % self.id
        self.simultaneous = None

    def init(self, config_get):
        self.alias = config_get(self.id, 'alias', None)
        self.deviceId = DeviceId(self.id, self.alias)

    def owRead(self, subPath, uncached=False):
        if not uncached:
            path = self.path
        else:
            path = self.pathUncached

        tS = time()
        raw = self.ow.read(path + subPath)
        tE = time()

        self.storeIoStatistic(OwIoStatistic(self.id, OwIoStatistic.OP_READ, uncached, tE-tS))

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

        self.storeIoStatistic(OwIoStatistic(self.id, OwIoStatistic.OP_WRITE, False, tE-tS))

        return data

    def owDir(self, subPath='', uncached=False):
        if not uncached:
            path = self.path
        else:
            path = self.pathUncached

        tS = time()
        entries = self.ow.dir(path + subPath)
        tE = time()

        self.storeIoStatistic(OwIoStatistic(self.id, OwIoStatistic.OP_DIR, uncached, tE-tS))

        return entries
        
    def owReadStr(self, subPath, uncached=False, strip=True):
        raw = self.owRead(subPath, uncached=uncached)

        data = bytes2str(raw)
        if strip:
            data = data.strip()

        return data

    def emitEvent(self, event):
        # TODO
        event.deviceId = self.deviceId
        self.log.info("%s: %s", self, event)

    def storeIoStatistic(self, stats):
        # just track the last one..
        self.lastIoStats = stats


    def on_seen(self):
        pass

    def on_alarm(self):
        self.log.warn("%s: Unhandled alarm" , str(self))

    def __str__(self):
        return "%s[%s]" % (self.__class__.__name__, self.id)


class OwBus(OwDevice):
    """Implements a Ow Bus as a OwDevice to keep some statistics and helpers."""
    def __init__(self, ow):
       super(OwBus, self).__init__(ow, None)
       self.path = "/"
       self.pathUncached = "/uncached/"

    def owDirAlarm(self, uncached=False):
        return self.owDir("alarm", uncached=uncached)

    def on_seen(self):
        raise Error("Not supposed to call on_seen on OwBus")

    def on_alarm(self):
        raise Error("Not supposed to call on_alarm on OwBus")

