# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
from base import OwDevice, OwEventBase
import time
from pyownet.protocol import bytes2str, str2bytez

def register(factory):
    factory.register("10", DS1820) # DS18S20
    factory.register("28", DS1820) # DS18B20
    factory.register("22", DS1820) # DS1822
    factory.register("3B", DS1820) # DS1825
    factory.register("42", DS1820) # DS28EA00

class OwTemperatureEvent(OwEventBase):
    """Describes an temperature reading"""
    def __init__(self, value):
        super(OwTemperatureEvent, self).__init__()
        self.value = value

    def __str__(self):
        return "OwTemperatureEvent[%s, %.2f C]" % (self.deviceId, self.value)

class DS1820(OwDevice):
    """Implements a DS1820, or actually any device with /temperature"""
    def __init__(self, ow, id):
        super(DS1820, self).__init__(ow, id)
        self.last = None

        # TODO: Configurable
        self.simultaneous = "temperature"

    def on_seen(self):
        if self.simultaneous == None:
            # Else, master handles temp-read via simult
            self.read_temperature()

    def read_temperature(self):
        data =  self.owReadStr('temperature', uncached=False)

        temp = float(data)
        if self.last == None:
            self.last = temp


        self.emitEvent(OwTemperatureEvent(temp))
#        self.log.debug("%s: Temp read in %.2fms -> Temp: %.3f (prev %.3f, diff %.3f)", \
#                self, self.lastIoStats.time*1000, temp, self.last, self.last-temp)

        self.last = temp

    def on_alarm(self):
        # Just disable alarms
        self.log.debug("%s: Silencing alarm", self)
        self.owWrite('templow', '-80')
        self.owWrite('temphigh', '125')
