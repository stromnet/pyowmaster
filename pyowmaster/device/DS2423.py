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
from pyowmaster.device.base import OwDevice, OwChannel
from pyowmaster.event.events import OwCounterEvent

def register(factory):
    factory.register("1D", DS2423)

class DS2423(OwDevice):
    """Handles DS2423 dual counter chip"""
    def __init__(self, ow, owid):
       super(DS2423, self).__init__(ow, owid)
       self.channels = (OwChannel(0, 'A', {}), OwChannel(1, 'B', {}))

    def on_seen(self, timestamp):
        """Read A,B counter"""
        counters = self.read_counters()

        self.emit_event(OwCounterEvent(timestamp, 'A', counters[0]))
        self.emit_event(OwCounterEvent(timestamp, 'B', counters[1]))

        #self.log.debug("%s: counters are %s", self, counters)

    def on_alarm(self, timestamp):
        # Normal DS2423 does not have alarm, but custom
        # AVR slave does. Silence it by reading it
        self.read_counters()

    def read_counters(self):
        return self.ow_read_int_list('counter.ALL', uncached=True)
