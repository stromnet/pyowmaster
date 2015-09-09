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
from base import OwDevice
from pio import *

def register(factory):
    factory.register("29", DS2408)

# Per-device alarm source + logical term
ALARM_SOURCE_NONE       = None
ALARM_SOURCE_PIO_OR     = 0
ALARM_SOURCE_LATCH_OR   = 1
ALARM_SOURCE_PIO_AND    = 2
ALARM_SOURCE_LATCH_AND  = 3

class DS2408(OwPIODevice):
    def __init__(self, ow, id):
        super(DS2408, self).__init__(True, ow, id)

        self.num_channels = 8

        # Only supported right now
        self.alarm_source = ALARM_SOURCE_LATCH_OR

    def _calculate_alarm_setting(self):
        """Based on the alarm_source instance property and the channel modes,
        calculate the desired alarm mode"""
        if self.alarm_source == ALARM_SOURCE_NONE:
            self.wanted_alarm = '00000000000'
        else:
            src_is_latch = self.alarm_source in (ALARM_SOURCE_LATCH_OR, ALARM_SOURCE_LATCH_AND)

            # Construct XYYYYYYYY
            # where X is trigger source + logical term (PIO or latch, AND or OR)
            # and Y is per channel selection (0,1=ignore, 2=low, 3=high)
            # Low order Y (last in string) is ch 0
            alarm_str = "%d" % self.alarm_source
            for ch in self.channels:
                chnum = ch.num
                
                if src_is_latch:
                    # Interested, and it's latch. Set Selected HIGH
                    alarm_str += "3"
                else:
                    # PIO as source, determine high/low polarity 
                    if ch.is_active_high:
                        alarm_str += "3" # Selected HIGH
                    else:
                        alarm_str += "2" # Selected LOW

            assert self.alarm_source >= 0 and self.alarm_source <= 3, "Bad alarm_source %d" % self.alarm_source 
            assert len(alarm_str) == 9, "Bad alarm_str %s" % alarm_str

            # Trim leading zeros
            self.wanted_alarm = alarm_str.lstrip('0')

        self.log.debug("%s: Wanted alarm calculated to %s", self, self.wanted_alarm)

    def check_alarm_config(self):
        """Ensure the DS2408 por property is 0. If not, we clear latches
        and ignore this alarm by returning True"""

        # Read POR status
        por = int(self.owReadStr('por', uncached=True))
        self.log.debug("%s: POR is %d", self, por)
        if por != 0:
            self.log.info("%s: power-up alarm, resetting & clearing latches", self)
            self.owWrite('por', 0)
            self.owWrite('out_of_testmode', 0) # Just to be sure...
            self.owWrite('latch.BYTE', '1')

        if super(DS2408, self).check_alarm_config():
            return True

        # Return True if we did POR fix, meaning ignore alarm condition
        return por != 0

