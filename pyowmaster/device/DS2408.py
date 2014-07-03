# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
from base import OwDevice
from switch_base import *

def register(factory):
    factory.register("29", DS2408)

# Per-device alarm source + logical term
ALARM_SOURCE_NONE       = None
ALARM_SOURCE_PIO_OR     = 0
ALARM_SOURCE_LATCH_OR   = 1
ALARM_SOURCE_PIO_AND    = 2
ALARM_SOURCE_LATCH_AND  = 3

class DS2408(OwSwitchDevice):
    def __init__(self, ow, id):
        super(DS2408, self).__init__(ow, id)

        self.channels = 8

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
            # where X is source + logical term (PIO or latch, AND or OR)
            # and Y is per channel selection
            # Low order Y (last in string) is ch 0
            alarm_str = "%d" % self.alarm_source
            for ch in range(self.channels, 0, -1):
                ch = ch - 1
                
                # src_channel 1 for A, 2 for B, 3 for A+B. thus, bitmask
                if src_is_latch:
                    # Interested, and it's latch. Set Selected HIGH
                    alarm_str+="3"
                else:
                    # PIO as source, determine high/low polarity 
                    if ((self.mode[ch] & MODE_ACTIVE_HIGH) != 0):
                        alarm_str+="3" # Selected HIGH
                    else:
                        alarm_str+="2" # Selected LOW

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
        if por != 0:
            self.log.info("%s: power-up alarm, resetting & clearing latches", self)
            self.owWrite('por', 0)
            self.owWrite('out_of_testmode', 0) # Just to be sure...
            self.owWrite('latch.BYTE', '1')

        if super(DS2408, self).check_alarm_config():
            return True

        # Return True if we did POR fix
        return por != 0

