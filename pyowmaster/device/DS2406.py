# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
from base import OwDevice
from switch_base import *

def register(factory):
    factory.register("12", DS2406)

# Alarm source mode, corresponds to set_alarm 2nd digit
ALARM_SOURCE_NONE       = None
ALARM_SOURCE_LATCH      = 1
ALARM_SOURCE_PIO        = 2
ALARM_SOURCE_SENSED     = 3

CH_NAMES = ['A', 'B']
CH_IDS= {'A':0, 'B':1}


class DS2406(OwSwitchDevice):
    def __init__(self, ow, id):
        super(DS2406, self).__init__(ow, id)

        # Cache for property channels
        self._channels = 0

        # Not configurable right now; alarm handler does not support other than latch.
        self.alarm_source = ALARM_SOURCE_LATCH

    @property
    def channels(self):
        """Returns the number of channels this devices has"""
        if self._channels:
            return self._channels

        self._channels = int(self.owReadStr('channels'))
        self.log.debug("%s: channels: %d", self, self._channels)
        return self._channels

    def _calculate_alarm_setting(self):
        """Based on the alarm_source instance property and the channel modes,
        calculate the desired alarm mode"""
        if self.alarm_source == ALARM_SOURCE_NONE:
            self.wanted_alarm = '000'
        else:
            src_channel = 0 # 1=A, 2=B, 3=A+B
            src_is_latch = (self.alarm_source == ALARM_SOURCE_LATCH)
            src_pol = 1 if src_is_latch else None

            for ch in range(self.channels):
                src_channel |= (1<<ch)
                if not src_is_latch:
                    # Sensed or PIO as source, determine high/low polarity 
                    pol = 1 if ((self.mode[ch] & MODE_ACTIVE_HIGH) != 0) else 0

                    if src_pol != None and src_pol != pol:
                        raise ConfigurationError("Cannot mix active high/low polarity when using alarm source other than latch")

                    src_pol = pol

            assert self.alarm_source >= 0 and self.alarm_source <= 3, "Bad alarm_source %d" % self.alarm_source 
            assert src_channel >= 0 and src_channel <= 3, "Bad src_channel %d" % src_channel
            assert src_pol >= 0 and src_pol <= 1, "Bad src_pol %d" % src_pol
            alarm_str = "%d%d%d" % \
                    (src_channel, self.alarm_source, src_pol)

            # Trim leading zeros
            self.wanted_alarm = alarm_str.lstrip('0')

        self.log.debug("%s: Wanted alarm calculated to %s", self, self.wanted_alarm)

    def _ch_translate(self, ch):
        return CH_NAMES[ch]

    def _ch_translate_rev(self, ch):
        return CH_IDS[ch.upper()]
