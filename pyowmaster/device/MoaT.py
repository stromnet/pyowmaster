# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
#
# Copyright 2015 Johan Ström
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
from pyowmaster.device.base import OwDevice
from pyowmaster.device.pio import *
from pyowmaster.event.events import OwAdcEvent, OwCounterEvent, OwPIOEvent
from pyowmaster.exception import InvalidChannelError
from pyownet.protocol import OwnetError
import time

ADC_MIN = 0
ADC_MAX = 65535

# Register of channel name => implementing classes
CH_TYPES = {}
def register(factory):
    factory.register("F0", MoaT)

    CH_TYPES['adc'] = MoaTADCChannel
    CH_TYPES['port'] = MoaTPortChannel
    CH_TYPES['count'] = MoaTCountChannel

class MoaT(OwDevice):
    """Implements communcations towards the MoaT device, a custom 1-Wire slave for Atmel AVR.

    The slave code can be found: https://github.com/M-o-a-T/owslave
    Requires owfs with MoaT support (currently not merged): https://github.com/M-o-a-T/owfs

    Handles the following types:
        - count
        - port
        - adc
        - status (device reboot reason)
        - alarm (alarm triggered by any of the above)

    Automatically scans the device's properties for it's configuration, and creates
    the appropriate channels.

    The count type only does periodic reading, and emits a OwCounterEvent for each channel
    on every scan. Alarms are silenced, but otherwise ignored.

    The port type supports input using the OwPIOEvent with on/off values. It also
    supports set_output from action handler.
    Events are only dispatched as results of alarms; no polling.

    The adc type can be configured either as plain ADC which reports an OwAdcEvent on
    every scan, in which case alarms are silenced, but ignored.
    Alternatively it can be configured with different "states", where each state is
    represented by an upper and a lower threshold. As long as the value is within these
    limits, the channel is said to be in that particular state.

    On each state change, an OwPIOEvent is emitted with the state name as value. This
    should be trigged by alarms, but if undetected change is seen in regular scan,
    the event will be emitted as well.
    For really quick state changes, where the value is returned to the previous state
    before we get a chance to read it, will still trigger an event with the nearest
    state, i.e. the one above or below the current one. This is possible since the
    alarm contains the threshold crossed (upper/lower). This can be disabled for each state.

    The status type may alarm when the device is resetted. On device reboot,
    the status will alarm and we will re-configure the device. Any alarms which
    arrive together with this status alarm will be ignored.
    """
    def __init__(self, ow, owid):
        super(MoaT, self).__init__(ow, owid)
        self.device_name = None
        self.ignore_next_silent_alarm = False

    def config(self, config):
        super(MoaT, self).config(config)

        # Keep config for future re-configuration
        self.dev_cfg = config

        # Clear reboot status; we're re-initing anyway now
        try:
            self.log.debug("%s: Clearing reboot reason indicator; initial configuration", self)
            self.ow_read_str('status/reboot', uncached=True)
        except OwnetError:
            # Ignore if node did not exist, i.e. no status support
            pass

        self.channels = {}
        self.init_channels(config)

    def reboot_detected(self, reason):
        """Call when reboot is detected, triggers re-init of all channels"""
        self.log.warn("%s: device rebooted, trigged by '%s'", self, reason)
        self.init_channels(self.dev_cfg)

    def init_channels(self, config):
        """Detect device configuration and initialize all channels"""

        self.device_name = self.ow_read_str('config/name', uncached=True)

        # Probe device for what kind of ports and channels it has
        # types is a new-line delimited list of <type>=<num>
        types = self.ow_read_str('config/types', uncached=True)

        # List of used channel types with read_all support
        self.combined_read_supported = []

        seen_channels = []

        for line in types.split('\n'):
            (ch_type, count) = line.split('=')
            count = int(count)
            self.log.debug("%s: got %d channels of type %s", self, count, ch_type)

            if ch_type not in CH_TYPES:
                self.log.debug("Ignoring unknown channel type %s", ch_type)
                continue

            # init from type registry
            clsref = CH_TYPES[ch_type]

            if hasattr(clsref, 'read_all'):
                # ensure it is a static method
                self.combined_read_supported.append(ch_type)

            # MoaT channels are numbered from 1
            for ch_num in range(1, count+1):
                ch_name = '%s.%d' % (ch_type, ch_num)

                # Only create on first init; else re-init
                ch = self.channels.get(ch_name, None)
                if not ch:
                    ch = clsref(ch_type, ch_num, config, self)
                    self.channels[ch.name] = ch
                    self.log.debug("%s: Configured ch %s", self, ch)

                seen_channels.append(ch.name)

        # Clean up dead channels, if we was re-inited
        for ch in self.channels.keys():
            if ch not in seen_channels:
                self.channels[ch].destroy()
                del self.channels[ch]

        # Now (re-)init each channel
        values_by_type = self.read_combined()
        for ch in self.channels.values():
            if ch.ch_type in values_by_type:
                ch.init(values_by_type[ch.ch_type][ch.ch_num - 1])
            else:
                ch.init()

        self.ignore_next_silent_alarm = True

    def read_combined(self):
        """Read every channel types 'all'  property to get all channel values in one shot
        Returns a dict with type => array of values"""
        values_by_type = {}
        for ch_type in self.combined_read_supported:
            all_values = CH_TYPES[ch_type].read_all(self)
            values_by_type[ch_type] = all_values

        return values_by_type


    def on_seen(self, timestamp):
        values_by_type = self.read_combined()

        for ch in self.channels.values():
            if ch.ch_type in values_by_type:
                ch.on_seen(timestamp, values_by_type[ch.ch_type][ch.ch_num - 1])
            else:
                ch.on_seen(timestamp)

    def on_alarm(self, timestamp):
        self.log.debug("%s: Device alarmed", self)
        # Find out which alarm sources we got
        sources = self.ow_read_str('alarm/sources', uncached=True)

        ignore_silent_alarm = self.ignore_next_silent_alarm
        self.ignore_next_silent_alarm = False
        if len(sources) == 0:
            if ignore_silent_alarm:
                # We just did a read, and might be given a spurous alarm.
                # If so, dont log it.
                return

            self.log.warn("%s: Device alarmed, but empty sources?", self)
            return

        self.log.debug("Handling sources '%s'", sources)

        sources = sources.split(',')

        if 'status' in sources:
            # Handled status first, as it might skip other alarms.
            sources.remove('status')
            sources.insert(0,'status')

        for port_type in sources:
            ports = self.ow_read_str('alarm/%s' % port_type, uncached=True)
            if len(ports) == 0:
                self.log.warn("%s: Device alarmed on %s, but non of the channels alarmed", self, port_type)
                continue

            ports = ports.split(',')

            # Read values of all the alarmed ones
            self.log.debug("Alarm on %s: %s", port_type, ports)

            for port_no in ports:
                # Special case for ADC, where it is prefixed with +/-
                adc_thresh = None
                if port_no[0] in ('-', '+'):
                    adc_thresh = port_no[0]
                    port_no = port_no[1:]

                if port_type == 'status':
                    if self.on_status_alarm(timestamp, port_no) == False:
                        # Abort alarm processing entirely
                        return
                    continue

                ch_name = '%s.%s' % (port_type, port_no)
                ch = self.channels.get(ch_name, None)
                if not ch:
                    self.log.debug("Ignoring unknown channel %s", ch_name)
                    continue

                # No reading of common pin state here.. Could be usable for port though?
                ch.on_alarm(timestamp, adc_thresh)

    def on_status_alarm(self, timestamp, status_name):
        val = self.ow_read_str('status/%s' % status_name, uncached=True)
        if status_name == 'reboot':
            # Device rebooted, and we now know why
            self.reboot_detected(val)

            # Thus no need to process further alarms.
        else:
            self.log.warn("%s: Unknown status field %s: %s", self, status_name, val)

        return False

    def set_output(self, channel, value):
        """Allow controlling of 'port' channels."""
        if isinstance(channel, MoaTChannel):
            ch = channel
        else:
            ch = self.channels[channel]

        if not hasattr(ch, 'set_output'):
            raise InvalidChannelError("Channel does not support output control")

        ch.set_output(value)


    def __str__(self):
        return "%s[%s; %s]" % (self.__class__.__name__, self.device_id, self.device_name)

class MoaTChannel(OwChannel):
    """A OwChannel for MoaT channels"""

    def __init__(self, ch_type, ch_num, config, device):
        """Create new MoaT channel.
        ch_type should be 'port', 'adc' or similar.
        ch_num should be the 1-based index of the channel"""

        self.num = None
        self.ch_type = ch_type
        self.ch_num = ch_num

        name = '%s.%d' % (ch_type, ch_num)
        ch_cfg = config.get(('devices', (device.id, device.type), name), {})

        # If set to single string, interpret as "mode" (mimics OwPIODevice)
        if isinstance(ch_cfg, str):
            ch_cfg = {'mode': ch_cfg}

        # If explicitly set to False, we mark this channel disabled.
        # The channel is still kept, so we can disable and silence any alarms.
        self.disabled = ch_cfg == False
        if self.disabled:
            # Everything underlying expects a dict
            ch_cfg = {}

        super(MoaTChannel, self).__init__(ch_num, name, ch_cfg)

        self.device = device
        self.log = self.device.log

    def init(self, value=None):
        """Called when channel should be (re)inited
        If the channel type supports grouped reading, the value parameter will be set with
        the value we've just read.
        """
        pass

    def on_seen(self, timestamp, value=None):
        """Called on every periodic device scan, where this device was seen.
        If the channel type supports grouped reading, the value parameter will be set with
        the value we've just read.
        """
        pass

    def on_alarm(self, timestamp, extra=None):
        pass


class MoaTPortChannel(MoaTChannel, OwPIOBase):
    """A OwChannel for MoaT Port channels, combined with OwPIOBase for configuration"""
    def __init__(self, ch_type, ch_num, config, device):
        super(MoaTPortChannel, self).__init__(ch_type, ch_num, config, device)

        # Init PIO properties from per-device config
        self.pio_base_init(self.config)

    @classmethod
    def read_all(cls, device):
        """Read all port values from this device"""
        values = device.ow_read_int_list('ports', uncached=True)
        device.log.debug("%s: read all ports: %s", device, values)
        return values

    def port_value_to_event_type(self, value):
        if value == self.is_active_high:
            event_type = OwPIOEvent.ON
        else:
            event_type = OwPIOEvent.OFF

    def init(self, value):
        """Initialize the port. Ports are always read grouped, so it always has an initial value"""
        self.value = value

        if not self.is_input_toggle and not self.is_output:
            return

        event_type = self.port_value_to_event_type(self.value)
        self.device.emit_event(OwPIOEvent(time.time(), self.name, event_type, True))

    def on_alarm(self, timestamp, extra=None):
        prev_value = self.value
        self.value = self.read()

        has_changed = self.value != prev_value

        if self.is_output or \
            (self.is_input and self.is_input_toggle):
            if has_changed:
                event_type = self.port_value_to_event_type(self.value)

        elif ch.is_input_momentary:
            # Alarm => assume trigged
            event_type = OwPIOEvent.TRIGGED
        else:
            raise RuntimeError("Invalid input mode %d for channel %s" % (self.mode, self))

        if event_type:
            self.device.emit_event(OwPIOEvent(timestamp, self.name, event_type, False))
        else:
            self.log.debug("%s %s: alarm ignored", self.device, self.name)

    def read(self):
        """Read latest value"""
        value = int(self.device.ow_read(self.name, uncached=True))
        self.log.debug("%s %s: Value: %d", self.device, self.name, value)
        return value

    def set_output(self, value):
        """Toggle an output port between 1/0 mode; what this means depends on device configuration"""
        if not self.is_output:
            raise InvalidChannelError("Channel not configured as output")

        active_high = self.is_active_high
        if (value and active_high) or (not value and not active_high):
            out_value = 1
        else:
            out_value = 0

        self.log.info("%s %s: Writing %d", self.device, self.name, out_value)
        self.device.ow_write(self.name, out_value)

    def __str__(self):
        alias = ""
        if self.alias:
            alias = " (alias %s)" % self.alias
        return "%s %s%s, mode=%s" % (self.__class__.__name__, self.name, alias, self.modestr())

class MoaTCountChannel(MoaTChannel):
    """A OwChannel for MoaT Count channels"""
    def __init__(self, ch_type, ch_num, config, device):
        super(MoaTCountChannel, self).__init__(ch_type, ch_num, config, device)

    def on_seen(self, timestamp):
        if self.disabled:
            return

        value = self.read()

        self.log.debug("%s %s: Value: %d", self.device, self.name, value)
        self.device.emit_event(OwCounterEvent(timestamp, self.name, value))

    def on_alarm(self, timestamp, extra=None):
        """Alarms on count channels are ignored for now"""
        self.read()

    def read(self):
        """Read value"""
        value = int(self.device.ow_read(self.name, uncached=True))
        self.log.debug("%s %s: Value: %d", self.device, self.name, value)
        return value

class MoaTADCChannel(MoaTChannel):
    """A OwChannel for MoaT ADC channels"""
    def __init__(self, ch_type, ch_num, config, device):
        super(MoaTADCChannel, self).__init__(ch_type, ch_num, config, device)

        # The thresholds we aim to use
        self.wanted_low_threshold = None
        self.wanted_high_threshold = None

        # Last read threaholds
        self.low_threshold = ADC_MAX
        self.high_threshold = ADC_MIN

        if self.disabled:
            return

        # Find states configuration under device config, either ID or fallback on device type,
        # and below that the channel name, or fallback channel type (adc), and key 'states'
        states = config.get(('devices', (self.device.id, self.device.type), ('adc', self.name), 'states'), None)
        if states:
            self.current_state = None
            if isinstance(states, str):
                # If configured as string, look for a common reference.
                # These can be placed under devices/MoaT/adc/state_template/<name>
                template_name = states
                states = config.get(('devices', self.device.type, 'adc', 'state_templates', template_name), None)
                if not states:
                    raise ConfigurationError("%s: Invalid ADC state reference %s" % (self.name, template_name))

            self.build_states(states)

    def build_states(self, states):
        """Read a number of states from the configuration

        Under channel config key 'states', an object with different
        states should be set. Each key is a state name, and each value should
        be an object with keys "low" and "high".

        Example, defining 4 different states.

            states:
                short:
                    high: 3000
                closed:
                    low: 3000
                    high: 38000
                open:
                    low: 38000
                    high: 45000
                cut:
                    low: 45000

        The states may also have the key 'guess' which can be set to False to
        prohibit guessing (see guess_state_entry).
        """
        self.states = []
        for state_name in states.keys():
            # Create internal repr of each state, tuple of (name,low,high)
            low = states.get((state_name, 'low'), ADC_MIN)
            high = states.get((state_name, 'high'), ADC_MAX)
            guess = states.get((state_name, 'guess'), True)
            self.states.append((state_name, low, high, guess))

        # Sort by low
        self.states.sort(lambda a,b: cmp(a[1], b[1]))

        # TODO: Check sanity?

    def get_state_entry(self, value):
        """Get the state entry which corresponds to the given value, or None if none is matching"""
        for s in self.states:
            if value >= s[1] and value <= s[2]:
                return s

        return None

    def guess_state_entry(self, adc_threshold_crossed):
        """Guess the state entry based on the current state and the threshold we crossed.
        Used only when alarm is received, but value was within the current threshold set.

        adc_threshold_crossed should be + or - for positive/negative threshold.

        Note that this will only guess one step down/up from current state; if more steps
        exist, it may get it wrong.
        Disable guessing by adding 'guess: False' to any state definition we should not use
        guessing on to get out from. Instead, the alarm will be ignored."""
        prev = None
        for n in range(len(self.states)):
            if self.states[n][0] != self.current_state:
                continue

            if self.states[n][3] == False:
                # Guess disabled for this state
                return None

            if adc_threshold_crossed == '-':
                # We've crossed lower threshold of this state, return previous one
                return self.states[max(0, n-1)]

            if adc_threshold_crossed == '+':
                # We've crossed upper threshold of this state, return next one
                return self.states[min(len(self.states)-1, n+1)]

        return None

    def get_event_types(self):
        """pywomaster.event.actionhandler uses this to determine which event types this channel may dispatch"""
        if not hasattr(self, 'states'):
            return ()

        return map(lambda x: x[0], self.states)

    @classmethod
    def read_all(cls, device):
        """Read all ADC values from a device. Note that this does NOT return thresholds!"""
        values = device.ow_read_int_list('adcs', uncached=True)
        device.log.debug("%s: read all adcs: %s", device, values)
        return values

    def read(self):
        """Read and return (value, slow_threshold, high_threshold)"""
        (value, low_threshold, high_threshold) = self.device.ow_read_int_list(self.name, uncached=True)
        if not self.disabled:
            self.log.debug("%s %s: Value: %d (low %d, high %d)",
                    self.device, self.name, value, low_threshold, high_threshold)

        return (value, low_threshold, high_threshold)

    def init(self, value):
        """Channel initialization; ensure the alarm config is proper"""
        self.value = value
        if hasattr(self, 'states'):
            s = self.get_state_entry(value)
            self.set_state(time.time(), s, True)
        else:
            # Disable alarms
            self.set_thresholds(ADC_MAX, ADC_MIN)

    def on_seen(self, timestamp, value):
        """ADCs can read all values, value is expected to be set"""
        self.value = value
        if self.disabled:
            return

        if not hasattr(self, 'states'):
            # Regular ADC mode, just emit the value
            self.device.emit_event(OwAdcEvent(timestamp, self.name, self.value))
        else:
            # For state mode, we do a check to ensure we are in the state we think
            # we are
            s = self.get_state_entry(value)
            if self.current_state != s[0]:
                # This may be valid, if we happened to scan at the same time an alarm
                # is trigged. However, the alarm has now been reset.
                self.log.debug("%s %s: Expected to be in state %s, was in state %s (value %d)",
                    self.device, self.name, self.current_state, s[0], value)
                self.device.ignore_next_silent_alarm = True
                self.set_state(timestamp, s, False)

    def on_alarm(self, timestamp, adc_threshold_crossed):
        (self.value, self.low_threshold, self.high_threshold) = self.read()

        new_state_ent = None
        if hasattr(self, 'states'):
            # find out what state we are in
            new_state_ent = self.get_state_entry(self.value)
            if new_state_ent is None:
                self.log.warn("%s %s: got alarm on value %d, does not match any configured state. Disabling thresholds",
                        self.device, self.name, self.value)
                self.set_thresholds(ADC_MAX, ADC_MIN)
                return

            if new_state_ent[0] == self.current_state:
                # No change, but we DID get an alarm. Too fast for our polling?
                # Find out which state we may have gone to by looking at adc_threshold_crossed
                # which is + or -
                guess_state_ent = self.guess_state_entry(adc_threshold_crossed)
                if guess_state_ent is None:
                    self.log.warn("%s %s: got %s alarm on value %d (%s), current state does not allow guessing. Ignoring",
                            self.device, self.name, adc_threshold_crossed, self.value, new_state_ent[0])
                    return

                self.log.debug("%s %s: got %s alarm on value %d (%s), guessing target state was %s",
                        self.device, self.name, adc_threshold_crossed, self.value,
                        new_state_ent[0], guess_state_ent[0])
                new_state_ent = guess_state_ent
            else:
                self.log.debug("%s %s: got %s alarm on value %d, matches new state %s",
                        self.device, self.name, adc_threshold_crossed, self.value,
                        new_state_ent[0])

            self.set_state(timestamp, new_state_ent, False)
        else:
            # Should not get alarms; Thresholds should already be disbled?
            self.log.warn("%s %s: got alarm on value %d, but thresholds should have been disabled",
                    self.device, self.name, self.value)
            self.set_thresholds(ADC_MAX, ADC_MIN)

    def set_state(self, timestamp, state_ent, is_reset):
        """Set the current state & emit an event announcing the change, then reconfigure thresholds"""
        self.log.debug("%s %s: now in state %s (prev %s)", self.device, self,
                state_ent[0], self.current_state)
        self.current_state = state_ent[0]

        ev = OwPIOEvent(timestamp, self.name, self.current_state, is_reset)
        self.device.emit_event(ev)

        # Calculate automatic thresholds and set them
        (low_threshold, high_threshold) = self.calculate_state_thresholds(\
                self.value, state_ent)
        self.set_thresholds(low_threshold, high_threshold)

    def calculate_state_thresholds(self, value, state_ent):
        """Calculate new thresholds based on state configuration and current value/state.
        """
        low_threshold = None
        high_threshold = None

        if state_ent is not None:
            low_threshold = state_ent[1]
            high_threshold = state_ent[2]
        else:
            self.log.warn("%s %s: value is outside of any predefined threshold sets: %d",
                    self.device, self.name, value)
            # Calculate some defaults surrounding this value
            low_threshold = max(ADC_MIN, value-5000)
            high_threshold = min(ADC_MAX, value+5000)

        return (low_threshold, high_threshold)

    def set_thresholds(self, low_threshold=None, high_threshold=None):
        """Write wanted thresholds to the device.

        If low/high params are set, we update wanted_xx_threshold with those values.
        This is later used in the check_alarm_config method.
        """
        if low_threshold != None: self.wanted_low_threshold = low_threshold
        if high_threshold != None: self.wanted_high_threshold = high_threshold

        # If we are equal to min or max, disable those thresholds, or we will just
        # re-trigger over and over (that is, if value = 0/ADC_MAX)
        if self.wanted_low_threshold in (None, ADC_MIN):  self.wanted_low_threshold = ADC_MAX
        if self.wanted_high_threshold in (None, ADC_MAX): self.wanted_high_threshold = 0

        self.log.debug("%s %s: Writing new thresholds (low %d, high %d)",
                self.device, self,
                self.wanted_low_threshold, self.wanted_high_threshold)

        self.device.ow_write(self.name, '%d,%d' % (self.wanted_low_threshold, self.wanted_high_threshold))

        # Expect written to be the new actuals
        self.low_threshold = self.wanted_low_threshold
        self.high_threshold = self.wanted_high_threshold

