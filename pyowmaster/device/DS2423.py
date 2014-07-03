# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
from base import OwDevice
from pyownet.protocol import bytes2str, str2bytez

def register(factory):
    factory.register("1D", DS2423)

class DS2423(OwDevice):
    """Handles DS2423 dual counter chip"""
    def __init__(self, ow, id):
       super(DS2423, self).__init__(ow, id)

    def on_seen(self):
        """Read A,B counter"""
        counters = self.readCounters()

        self.log.debug("%s: counters are %s", self, counters)

    def on_alarm(self):
        # Normal DS2423 does not have alarm, but custom
        # AVR slave does. Silence it by reading it
        self.readCounters()

    def readCounters(self):
        counters = self.owReadStr('counter.ALL', uncached=True)
        return map(int, map(unicode.strip, counters.split(',')))
