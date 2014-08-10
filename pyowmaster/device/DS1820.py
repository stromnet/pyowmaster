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
from base import OwDevice
from ..event.events import OwTemperatureEvent

def register(factory):
    # Misc names, but we follow OWFS source code and call ourselfs 1820 internally.
    factory.register("10", DS1820) # DS18S20
    factory.register("28", DS1820) # DS18B20
    factory.register("22", DS1820) # DS1822
    factory.register("3B", DS1820) # DS1825
    factory.register("42", DS1820) # DS28EA00

# Min/Max temperatures per unit
TEMP_MIN = {'C':-55, 'F': -67, 'R':392, 'K':218}
TEMP_MAX = {'C':125, 'F': 257, 'R':716, 'K':398}


class DS1820(OwDevice):
    """Implements reading of a DS1820 and similar"""
    def __init__(self, ow, id):
        super(DS1820, self).__init__(ow, id)
        self.last = None

        # TODO: Configurable
        self.simultaneous = "temperature"

    def config(self, config_get):
        super(DS1820, self).config(config_get)

        self.unit = config_get('owmaster', 'temperature_unit', 'C').upper()
        self.min_temp = config_get((self.id, 'DS1820'), 'min_temp', TEMP_MIN[self.unit])
        self.max_temp = config_get((self.id, 'DS1820'), 'max_temp', TEMP_MAX[self.unit])

        self.log.debug("%s: configured with unit %s, min %.2f, max %.2f",
                self, self.unit,
                self.min_temp,
                self.max_temp)

    def on_seen(self, timestamp):
        if self.simultaneous == None:
            # Else, master handles temp-read via simult
            self.read_temperature(timestamp)

    def read_temperature(self, timestamp):
        data =  self.owReadStr('temperature', uncached=False)

        temp = float(data)

        # Check if it is sane
        if temp < self.min_temp or temp > self.max_temp:
            self.log.warn("%s: outside of sane limits, ignoring (actual: %.2f %s, min: %.2f, max: %.2f)", \
                    self, temp, self.unit, self.min_temp, self.max_temp)
            return

        if self.last == None:
            self.last = temp

        self.emitEvent(OwTemperatureEvent(timestamp, temp, self.unit))
        #self.log.debug("%s: Temp read in %.2fms -> Temp: %.3f (prev %.3f, diff %.3f)", \
        #        self, self.lastIoStats.time*1000, temp, self.last, self.last-temp)

        self.last = temp

    def on_alarm(self, timestamp):
        # Just disable alarms
        self.log.debug("%s: Silencing alarm", self)
        self.owWrite('templow', TEMP_MIN[self.unit])
        self.owWrite('temphigh', TEMP_MAX[self.unit])

