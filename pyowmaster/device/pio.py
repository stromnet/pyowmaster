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
from pyowmaster.device.base import OwChannel, OwDevice
from pyowmaster.event.events import OwPIOEvent
from pyowmaster.exception import ConfigurationError, InvalidChannelError
import logging, time

# Modes of operation, per channel
PIO_MODE_OUTPUT             = 0b00001
PIO_MODE_INPUT              = 0b00010
PIO_MODE_INPUT_MOMENTARY    = 0b00100 | PIO_MODE_INPUT
PIO_MODE_INPUT_TOGGLE       = 0b01000 | PIO_MODE_INPUT

PIO_MODE_ACTIVE_LOW   = 0b00000
PIO_MODE_ACTIVE_HIGH  = 0b10000


def test_bits(value, mask):
    return (value & mask) == mask


class OwPIOBase(object):
    """A shared base class for basic PIO pin channels"""

    def pio_base_init(self, cfg):
        """Init a new OwPIOBase, with a "mode" configuration parsed
        from the cfg dict key 'mode'

        To be called from __init__ in sub class.

        The mode string should be a combination of the following strings:
            input momentary (default)
            input toggle
        or
            output

        combined with
            active low (default)
            active high

        """
        modestr = cfg.get('mode', 'input momentary')
        self.mode = self.parse_pio_mode(modestr)

        # Updated in OwPIODevice.on_alarm, or similar
        self.value = None
        self.state = None

    def parse_pio_mode(self, mode):
        cfg = 0
        if mode.find('output') != -1:
            cfg |= PIO_MODE_OUTPUT
        else:
            # Default input
            cfg |= PIO_MODE_INPUT

            if mode.find('toggle') != -1:
                cfg |= PIO_MODE_INPUT_TOGGLE
            else:
                # Default momentary
                cfg |= PIO_MODE_INPUT_MOMENTARY

        if mode.find('active low') != -1:
            cfg |= PIO_MODE_ACTIVE_LOW
        elif mode.find('active high') != -1:
            cfg |= PIO_MODE_ACTIVE_HIGH
        else:
            # For input, "ON" means connected to GND (only option in parsite-powered nets)
            # For outputs, "ON" means PIO transistor is active and the sensed output is LOW.
            cfg |= PIO_MODE_ACTIVE_LOW

        return cfg

    def modestr(self):
        if self.is_output:
            s = "output "
        elif self.is_input:
            s = "input "
            if self.is_input_toggle:
                s += "toggle "
        else:
            raise ConfigurationError("Unknown mode %d" % self.mode)

        if self.is_active_low:
            s += "active low"
        elif self.is_active_high:
            s += "active high"

        return s

    def get_event_types(self):
        """pywomaster.event.actionhandler uses this to determine which PIO event types this channel may dispatch"""
        if self.is_input_momentary:
            return ('trigged',)
        else:
            return ('on', 'off')

    @property
    def is_output(self):
        return test_bits(self.mode, PIO_MODE_OUTPUT)

    @property
    def is_input(self):
        return test_bits(self.mode, PIO_MODE_INPUT)

    @property
    def is_input_momentary(self):
        return test_bits(self.mode, PIO_MODE_INPUT_MOMENTARY)

    @property
    def is_input_toggle(self):
        return test_bits(self.mode, PIO_MODE_INPUT_TOGGLE)

    @property
    def is_active_high(self):
        return test_bits(self.mode, PIO_MODE_ACTIVE_HIGH)

    @property
    def is_active_low(self):
        return not test_bits(self.mode, PIO_MODE_ACTIVE_HIGH)


class OwPIOChannel(OwPIOBase, OwChannel):
    """A OwChannel for devices with PIO"""
    def __init__(self, num, name, cfg):
        """Create a new OwPIOChannel, a OwChannel with an OwPIOBase"""
        super(OwPIOChannel, self).__init__(num, name, cfg)
        self.pio_base_init(cfg)

    def is_set(self, value):
        """Given a bitmask value, return this channels bit position value as a True(1)/False(0)"""
        return (value & (1 << self.num)) != 0

    def __str__(self):
        return "%s %s (alias %s), mode=%s [%s,%s]" % (self.__class__.__name__, self.name, self.alias, self.modestr(), self.value, self.state)


class OwPIODevice(OwDevice):
    """Abstract base class for use with DS2406, DS2408 and similar PIO devices.

    Subclass must implement:

        - A property named "num_channels" must exist, which tells how
            many channels this device has.

        - Method _calculate_alarm_setting
        - Method _on_alarm_handled
    """
    def __init__(self, _alarm_supported, ow, owid):
        """Subclass should set the _alarm_supported flag acordingly"""
        super(OwPIODevice, self).__init__(ow, owid)

        self.alarm_supported = _alarm_supported
        self.inital_setup_done = False
        self._last_sensed = None

    def config(self, config):
        super(OwPIODevice, self).config(config)

        self.channels = []
        # For each channel on the device, create a OwPIOChannel object and put in channels list
        for chnum in range(self.num_channels):
            chname = str(self._ch_translate(chnum))
            # Primarily read section with <device-id>:<ch.X>,
            # fall back on <device-type>:<ch.X>
            # The value should be a mode-string, or a dict which is passed to  OwPIOChannel
            cfgval = config.get(('devices', (self.id, self.type), 'ch.' + chname), {})
            if isinstance(cfgval, str):
                cfgval = {'mode': cfgval}

            sw = OwPIOChannel(chnum, chname, cfgval)
            self.log.debug("Ch %d configured as %s", chnum, sw)

            self.channels.append(sw)

        if self.alarm_supported:
            self._calculate_alarm_setting()

            # Apply alarm config directly
            self.check_alarm_config()
        else:
            for ch in self.channels:
                if ch.is_input:
                    self.log.warn("Channel configured as Input, but this device does not have alarm support. No polling implemented!")
                    break

    def _calculate_alarm_setting(self):
        """Override this and set self.wanted_alarm, this will be feed to set_alarm"""
        self.wanted_alarm = None  # silence pylint
        raise NotImplementedError("_calculate_alarm_setting property must be implemented by sub class")

    def on_seen(self, timestamp):
        # We have nothing to do here
        if not self.alarm_supported:
            return

        # But we are using alarm, ensure proper config..
        self.check_alarm_config()

        if self._last_sensed is not None:
            # xXX: If already read, skip re-read... When is this
            # required? On re-start?
            return

        # refresh sensed; mainly for startup
        sensed = int(self.ow_read_str('sensed.BYTE', uncached=True))
#        if self._last_sensed != None and self._last_sensed != sensed:
#            # XXX: Racey with alarm
#            self.log.warn("%s: Sensed altered without on_alarm being notified. Last=%d, now=%d",\
#                    self, self._last_sensed, sensed)
#
#        elif self._last_sensed == None:
#            self.log.debug("last_sensed inited %d", sensed)

        self._last_sensed = sensed

    def _emit_init_state(self, sensed):
        """During alarm reconfigure (due to startup, or device reset), emit special events
        for all Toggle inputs, and outputs, to let global system know it may have changed"""
        timestamp = time.time()
        for ch in self.channels:
            ch_sensed = ch.is_set(sensed)
            ch.value = ch_sensed

            if not ch.is_input_toggle and not ch.is_output:
                continue

            ch_active_level = ch.is_active_high

            if ch_sensed == ch_active_level:
                event_type = OwPIOEvent.ON
            else:
                event_type = OwPIOEvent.OFF

            event = OwPIOEvent(timestamp, ch.name, event_type, True)
            self.log.debug("%s: ch %s event: %s",
                           self, ch.name, event_type)
            self.emit_event(event)

            ch.state = event_type

    def on_alarm(self, timestamp):
        if not self.alarm_supported:
            self.log.error("%s: Ignoring alarm, device should not get alarms!", self)
            return

        if self.check_alarm_config():
            self.log.warn("%s: Ignoring alarm, device was not ready", self)
            return

        # Read latch + sensed
        # XXX: in owlib DS2406 code we read register,
        # and could then read the uncached sensed.byte to get
        # the truely same sensed.
        # For DS2408 however, these are separate reads operations,
        # even if all data is read at both times
        latch = int(self.ow_read_str('latch.BYTE', uncached=True))
        sensed = int(self.ow_read_str('sensed.BYTE', uncached=True))

        # And clear the alarm
        self.ow_write('latch.BYTE', '1')

        last_sensed = self._last_sensed

        self.log.debug("%s: alarmed, latch=%d, sensed=%d, last_sensed=%s",
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
        for ch in self.channels:
            chnum = ch.num
            mode = ch.mode
            is_input = ch.is_input
            is_output = ch.is_output

            # 1 = True
            # 0 = False
            ch_latch = ch.is_set(latch)
            if not ch_latch:
                # Our latch was not triggered
                continue

            ch_sensed = ch.is_set(sensed)
            ch_active_level = ch.is_active_high
            ch_last_sensed = ch.is_set(last_sensed) if last_sensed is not None else None
            ch_has_changed = ch_last_sensed != ch_sensed if ch_last_sensed is not None else None

            ch.value = ch_sensed

            event_type = None
            if is_output or (is_input and ch.is_input_toggle):
                if ch_has_changed != False:
                    if ch_sensed == ch_active_level:
                        event_type = OwPIOEvent.ON
                    else:
                        event_type = OwPIOEvent.OFF

                ch.state = event_type

            elif ch.is_input_momentary:
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
                    event_type = OwPIOEvent.TRIGGED
            else:
                raise RuntimeError("Invalid input mode %d for channel %s" % (mode, ch))

            if event_type:
                event = OwPIOEvent(timestamp, ch.name, event_type)
                self.log.debug("%s: ch %s event: %s",
                               self, ch.name, event_type)
                self.emit_event(event)
            else:
                self.log.debug("%s: channel %s latch change ignored", self, ch)

    def check_alarm_config(self):
        """Ensure the alarm property is configured as intended.
        Returns True if change was applied, False if it was correct"""
        alarm = self.ow_read_str('set_alarm', uncached=True)

        reconfigured = False
        if alarm != self.wanted_alarm:
            self.log.log((logging.WARNING if self.inital_setup_done else logging.INFO),
                         "%s: reconfiguring alarm from %s to %s", self, alarm, self.wanted_alarm)

            self.ow_write('set_alarm', self.wanted_alarm)
            # And clear any alarm if already set
            self.ow_write('latch.BYTE', '1')

            reconfigured = True

        if reconfigured or not self.inital_setup_done:
            # Emit current state of all devices
            sensed = int(self.ow_read_str('sensed.BYTE', uncached=True))
            self._emit_init_state(sensed)

        self.inital_setup_done = True
        return reconfigured

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
        if isinstance(channel, OwPIOChannel):
            ch = channel
        else:
            ch_num = self._ch_translate_rev(channel)
            ch = self.channels[ch_num]

        if not ch.is_output:
            raise InvalidChannelError("Channel not configured as output")

        active_high = ch.is_active_high
        if (value and active_high) or (not value and not active_high):
            # PIO off => external pull-up possible => "high"
            out_value = 0
        else:
            # PIO on => pulled to ground => "low"
            out_value = 1

        self.log.info("%s: Writing PIO.%s = %d", self, ch.name, out_value)
        self.ow_write('PIO.%s' % ch.name, out_value)
