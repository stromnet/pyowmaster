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
from ..event.events import OwSwitchEvent
from collections import namedtuple

# Modes of operation, per channel
MODE_OUTPUT             = 0b00001
MODE_INPUT              = 0b00010
MODE_INPUT_MOMENTARY    = 0b00100 | MODE_INPUT
MODE_INPUT_TOGGLE       = 0b01000 | MODE_INPUT

MODE_ACTIVE_LOW   = 0b00000
MODE_ACTIVE_HIGH  = 0b10000


def parse_switch_config(cfgstr):
    cfg = 0
    if cfgstr.find('output') != -1:
        cfg |= MODE_OUTPUT
    else:
        # Default input
        cfg |= MODE_INPUT

        if cfgstr.find('toggle') != -1:
            cfg |= MODE_INPUT_TOGGLE
        else:
            # Default momentary
            cfg |= MODE_INPUT_MOMENTARY
    
    if cfgstr.find('active low') != -1:
        cfg |= MODE_ACTIVE_LOW
    elif cfgstr.find('active high') != -1:
        cfg |= MODE_ACTIVE_HIGH
    else:
        # For input, "ON" means connected to GND (only option in parsite-powered nets)
        # For outputs, "ON" means PIO transistor is active and the sensed output is LOW.
        cfg |= MODE_ACTIVE_LOW

    return cfg

class OwSwitchDevice(OwDevice):
    """Abstract base class for use with DS2406 and DS2408.

    Subclass must implement:

        - A property named "channels" must exist, which tells how
            many channels this device has.

        - Method _calculate_alarm_setting
        - Method _on_alarm_handled
    """
    def __init__(self, ow, id):
        super(OwSwitchDevice, self).__init__(ow, id)

        self._last_sensed = None

    def config(self, config_get):
        super(OwSwitchDevice, self).config(config_get)

        self.mode = []
        for ch in range(self.channels):
            chname = str(self._ch_translate(ch))
            cfg = parse_switch_config(config_get(self.id, "ch." + chname, 'input momentary'))
            self.mode.append(cfg)

        self._calculate_alarm_setting()

    def _calculate_alarm_setting(self):
        """Override this and set self.wanted_alarm, this will be feed to set_alarm"""
        self.wanted_alarm = None # silence pylint
        raise NotImplementedError("_calculate_alarm_setting property must be implemented by sub class")

    def on_seen(self, timestamp):
        if self._last_sensed != None:
            # xXX: If already read, skip re-read... When is this
            # required? On re-start?
            return

        # We have nothing to do here; we are only using alarm
        # However, ensure proper config..
        self.check_alarm_config()

        # refresh sensed; mainly for startup
        sensed = int(self.owReadStr('sensed.BYTE', uncached=True))
#        if self._last_sensed != None and self._last_sensed != sensed:
#            # XXX: Racey with alarm
#            self.log.warn("%s: Sensed altered without on_alarm being notified. Last=%d, now=%d",\
#                    self, self._last_sensed, sensed)
#
#        elif self._last_sensed == None:
#            self.log.debug("last_sensed inited %d", sensed)
        self._last_sensed = sensed
    
    def on_alarm(self, timestamp):
        if self.check_alarm_config():
            self.log.warn("%s: Ignoring alarm, device was not ready", self)
            return

        # Read latch + sensed
        # XXX: in owlib DS2406 code we read register, 
        # and could then read the uncached sensed.byte to get
        # the truely same sensed.
        # For DS2408 however, these are separate reads operations,
        # even if all data is read at both times
        latch = int(self.owReadStr('latch.BYTE', uncached=True))
        sensed = int(self.owReadStr('sensed.BYTE', uncached=True))

        # And clear the alarm
        self.owWrite('latch.BYTE', '1')

        last_sensed = self._last_sensed

        self.log.debug("%s: alarmed, latch=%d, sensed=%d, last_sensed=%s", \
                self, latch, sensed, last_sensed)

        self._handle_alarm(timestamp, latch, sensed, last_sensed)

        self._last_sensed = sensed

    def _ch_translate(self, ch):
        """Optional overridable channel name function; return channel identifier based on 0-based index"""
        return ch

    def _ch_translate_rev(self, ch):
        """Optional overridable channel resolve function; return 0-baesd index based on channel identifier"""
        return int(ch)

    def _handle_alarm(self, timestamp, latch, sensed, last_sensed):
        for ch in range(self.channels):
            mode = self.mode[ch]
            is_input = ((mode & MODE_INPUT) == MODE_INPUT)
            is_output = ((mode & MODE_OUTPUT) == MODE_OUTPUT)

            # 1 = True
            # 0 = False
            ch_latch = latch & (1<<ch) != 0
            if not ch_latch:
                # Our latch was not triggered
                continue

            ch_sensed = sensed & (1<<ch) != 0
            ch_active_level = (mode & MODE_ACTIVE_HIGH) == MODE_ACTIVE_HIGH
            ch_last_sensed = last_sensed & (1<<ch) != 0 if last_sensed != None else None
            ch_has_changed = ch_last_sensed != ch_sensed if ch_last_sensed != None else None

            if is_output or \
                (is_input and ((mode & MODE_INPUT_TOGGLE) == MODE_INPUT_TOGGLE)):
                if ch_has_changed != False:
                    if ch_sensed == ch_active_level:
                        self.emitEvent(OwSwitchEvent(timestamp, self._ch_translate(ch), OwSwitchEvent.ON))
                    else:
                        self.emitEvent(OwSwitchEvent(timestamp, self._ch_translate(ch), OwSwitchEvent.OFF))

            elif (mode & MODE_INPUT_MOMENTARY) == MODE_INPUT_MOMENTARY:
                # Two scenarios we must handle (active_level=1):
                #   1. Button is pressed [latch triggers]
                #   2. Button is released [latch already triggered, no change]
                #   3. We get the alarm, clear latch, sensed=0 (ch_sensed != ch_active_level)
                # or
                #   1. Button is pressed [latch triggers]
                #   2. We get alarm, clear latch, sensed=1 (ch_sensed == ch_active_level)
                #   3. Button is released [latch triggers]
                #   4. We get alarm, clear latch, sensed=0 (ch_last_sensed == ch_active_level)
                #
                # In the second scenario, we want to avoid trig on the second latch

                if ch_sensed == ch_active_level or ch_last_sensed != ch_active_level:
                    self.emitEvent(OwSwitchEvent(timestamp, self._ch_translate(ch), OwSwitchEvent.TRIGGED))
                else:
                    self.log.debug("%s: channel %d latch change ignored", self, ch)
            else:
                raise RuntimeError("Invalid input mode %d for channel %d" % (mode, ch))

    def check_alarm_config(self):
        """Ensure the alarm property is configured as intended.
        Returns True if change was applied, False if it was correct"""
        alarm = self.owReadStr('set_alarm', uncached=True)

        if alarm != self.wanted_alarm:
            self.log.info("%s: reconfiguring alarm from %s to %s", self, alarm, self.wanted_alarm)
            self.owWrite('set_alarm', self.wanted_alarm)
            return True
        
        return False

    def set_output(self, channel, value):
        """Control a channel configured as output, setting the new value to ON or OFF.
        The actual PIO state is controlled by the output "active high" or "active low" configuration
        mode.

        value should be True or False. If set to true, we set the output "active".

        If channel is not configured as output, an exception is thrown.

        Note that "active low" refers to the actual logic level, i.e this will 
        write PIO.xx 1, to enable the transistor, pulling down the line, and activating
        something by grounding the pin (low).
        """
        ch = self._ch_translate_rev(channel)
        mode = self.mode[ch]

        if not ((mode & MODE_OUTPUT) == MODE_OUTPUT):
            raise Exception("Channel not configured as output")

        active_high = (mode & MODE_ACTIVE_HIGH) == MODE_ACTIVE_HIGH
        if (value and active_high) or (not value and not active_high):
            # PIO off => external pull-up possible => "high"
            out_value = 0
        else:
            # PIO on => pulled to ground => "low"
            out_value = 1

        channel = self._ch_translate(ch)
        self.log.info("%s: Writing PIO.%s = %d", self, channel, out_value)
        self.owWrite('PIO.%s' % channel, out_value)

