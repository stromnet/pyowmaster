# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
from base import OwDevice
from ..event.events import OwCounterEvent

def register(factory):
    factory.register("1D", DS2423)

class DS2423(OwDevice):
    """Handles DS2423 dual counter chip"""
    def __init__(self, ow, id):
       super(DS2423, self).__init__(ow, id)

    def on_seen(self, timestamp):
        """Read A,B counter"""
        counters = self.readCounters()

        self.emitEvent(OwCounterEvent(timestamp, 'A', counters[0]))
        self.emitEvent(OwCounterEvent(timestamp, 'B', counters[1]))

        self.log.debug("%s: counters are %s", self, counters)

    def on_alarm(self, timestamp):
        # Normal DS2423 does not have alarm, but custom
        # AVR slave does. Silence it by reading it
        self.readCounters()

    def readCounters(self):
        counters = self.owReadStr('counter.ALL', uncached=True)
        return map(int, map(unicode.strip, counters.split(',')))
