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
from pyowmaster.event.events import OwAdcEvent, OwCounterEvent

ADC_MIN = 0
ADC_MAX = 65535

def register(factory):
    factory.register("F0", MoaT)

class MoaT(OwDevice):
    def __init__(self, ow, owid):
        super(MoaT, self).__init__(ow, owid)
        self.device_name = None

    def config(self, config):
        super(MoaT, self).config(config)
        self.channels = {}

        self.device_name = self.ow_read_str('config/name', uncached=True)

        # Probe device for what kind of ports and channels it has
        # types is a new-line delimited list of <type>=<num>
        types = self.ow_read_str('config/types', uncached=True)
        for line in types.split('\n'):
            (ch_type, count) = line.split('=')
            count = int(count)
            self.log.debug("%s has %d channels of type %s", self, count, ch_type)
            # MoaT channels are numbered from 1
            for ch_num in range(1, count+1):
                ch_name = '%s.%d' % (ch_type, ch_num)

                if ch_type == 'adc':
                    ch = MoaTADCChannel(ch_type, ch_num, config, self)
                elif ch_type == 'port':
                    ch = MoaTPortChannel(ch_type, ch_num, config, self)
                elif ch_type == 'count':
                    ch = MoaTCountChannel(ch_type, ch_num, config, self)
                else:
                    continue

                self.channels[ch.name] = ch
                ch.check_alarm_config()

    def on_seen(self, timestamp):
        for ch in self.channels.values():
            ch.on_seen(timestamp)

    def on_alarm(self, timestamp):
        self.log.debug("Device alarmed")
        # Find out which alarm sources we got
        sources = self.ow_read_str('alarm/sources', uncached=True).split(',')
        for port_type in sources:
            ports = self.ow_read_str('alarm/%s' % port_type, uncached=True).split(',')

            # Read values of all the alarmed ones
            self.log.debug("Alarm on %s: %s", port_type, ports)

            for port_no in ports:
                # Special case for ADC, where it is prefixed with +/-
                adc_thresh = None
                if port_no[0] in ('-', '+'):
                    adc_thresh = port_no[0]
                    port_no = port_no[1:]

                ch_name = '%s.%s' % (port_type, port_no)
                ch = self.channels.get(ch_name, None)
                if not ch:
                    self.log.debug("Ignoring unknown channel %s", ch_name)
                    continue

                ch.on_alarm(timestamp)


    def __str__(self):
        return "%s[%s; %s]" % (self.__class__.__name__, self.device_id, self.device_name)

class MoaTChannel(OwChannel):
    """A OwChannel for MoaT channels"""

    def __init__(self, ch_type, ch_num, config, device):
        """Create new MoaT channel.
        ch_type should be 'port', 'adc' or similar.
        ch_num should be the 1-based index of the channel"""

        name = '%s.%d' % (ch_type, ch_num)
        ch_cfg = config.get(('devices', (device.id, device.type), name), {})

        super(MoaTChannel, self).__init__(ch_num, name, ch_cfg)

        self.device = device
        self.log = self.device.log

    def on_seen(self, timestamp):
        self.check_alarm_config()

    def on_alarm(self, timestamp):
        pass

    def check_alarm_config(self, inital=False):
        pass


class MoaTPortChannel(MoaTChannel):
    """A OwChannel for MoaT Port channels"""
    def __init__(self, ch_type, ch_num, config, device):
        super(MoaTPortChannel, self).__init__(ch_type, ch_num, config, device)

    def on_alarm(self, timestamp):
        self.read()

    def read(self):
        """Read and update value"""
        value = int(self.device.ow_read(self.name, uncached=True))
        self.log.debug("Value of %s: %d",
                self.name, value)

        self.value = value

class MoaTCountChannel(MoaTChannel):
    """A OwChannel for MoaT Count channels"""
    def __init__(self, ch_type, ch_num, config, device):
        super(MoaTCountChannel, self).__init__(ch_type, ch_num, config, device)

    def on_seen(self, timestamp):
        self.read()
        ev=OwCounterEvent(timestamp, self.name, self.value)

        self.log.debug("Emitting event %s", ev)
        self.device.emit_event(ev)

    def on_alarm(self, timestamp):
        # Just silence it for now
        self.read()

    def read(self):
        """Read and update value"""
        value = int(self.device.ow_read(self.name, uncached=True))
        self.log.debug("Value of %s: %d",
                self.name, value)

        self.value = value

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

        # Find states configuration under device config, either ID or fallback on device type,
        # and below that the channel name, or fallback channel type (adc), and key 'states'
        states = config.get(('devices', (self.device.id, self.device.type), ('adc', self.name), 'states'), None)
        if states:
            if isinstance(states, str):
                # If configured as string, look for a common reference.
                # These can be placed under devices/MoaT/adc/state_template/<name>
                template_name = states
                states = config.get(('devices', self.device.type, 'adc', 'state_templates', template_name), None)
                if not states:
                    raise ConfigurationError("%s: Invalid ADC state reference %s" % (self.name, template_name))

            self.configure_states(states)

    def configure_states(self, states):
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
        """
        self.states = []
        for state_name in states.keys():
            # Create internal repr of each state, tuple of (name,low,high)
            low = states.get((state_name, 'low'), ADC_MIN)
            high = states.get((state_name, 'high'), ADC_MAX)
            self.states.append((state_name, low, high))

        # Sort by low
        self.states.sort(lambda a,b: cmp(a[1], b[1]))

        # Check sanity?

    def on_seen(self, timestamp):
        super(MoaTADCChannel, self).on_seen(timestamp)

        # on_seen should call check_alarm_config, which calls read
        # Check if we should emit any events
        if not hasattr(self, 'states'):
            # Regular ADC mode, just emit the value
            self.device.emit_event(OwAdcEvent(timestamp, self.name, self.value))

    def on_alarm(self, timestamp):
        self.read()

        # Calculate possibly new thresholds and set them
        (low_threshold, high_threshold) = self.calculate_auto_thresholds()
        self.set_thresholds(low_threshold, high_threshold)

    def calculate_auto_thresholds(self):
        """Calculate new thresholds based on configuration and current value.
        Note that read() must be called prior to this to have an accurate and current value"""
        low_threshold = None
        high_threshold = None
        if hasattr(self, 'states'):
            for s in self.states:
                if self.value >= s[1] and self.value <= s[2]:
                    # Good set!
                    low_threshold = s[1]
                    high_threshold = s[2]
                    self.log.info("%s %s is in state %s", self.device, self, s[0])
                    break

            if low_threshold == None:
                self.log.warn("%s value is outside of any predefined threshold sets: %d", self, self.value)
                # Calculate some defaults surrounding this value
                low_threshold = max(ADC_MIN, self.value-5000)
                high_threshold = min(ADC_MAX, self.value+5000)

        # If we are equal to min or max, disable those thresholds, or we will just
        # re-trigger over and over (that is, if value = 0/ADC_MAX)
        if low_threshold in (None, ADC_MIN):  low_threshold = ADC_MAX
        if high_threshold in (None, ADC_MAX): high_threshold = 0

        return (low_threshold, high_threshold)

    def set_thresholds(self, low_threshold=None, high_threshold=None):
        """Write wanted thresholds to the device.

        If low/high params are set, we update wanted_xx_threshold with those values.
        """
        if low_threshold != None: self.wanted_low_threshold = low_threshold
        if high_threshold != None: self.wanted_high_threshold = high_threshold

        self.log.debug("Writing new thresholds for ADC %d (low %d, high %d)",
                self.num,
                self.wanted_low_threshold, self.wanted_high_threshold)

        self.device.ow_write(self.name, '%d,%d' % (self.wanted_low_threshold, self.wanted_high_threshold))

        self.low_threshold = self.wanted_low_threshold
        self.high_threshold = self.wanted_high_threshold

    def read(self):
        """Read values, and update the properties value, low_threshold, high_threshold"""
        (value, low_threshold, high_threshold) = self.device.ow_read_int_list(self.name, uncached=True)
        self.log.debug("Value of %s: %d (low %d, high %d)",
                self.name, value, low_threshold, high_threshold)

        self.value = value
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

    def check_alarm_config(self):
        """Read current values, and check if the thresholds are within expected limits"""
        self.read()

        if self.wanted_low_threshold == None and self.wanted_high_threshold == None:
            # Initial startup/setup, configure thresholds
            (low_threshold, high_threshold) = self.calculate_auto_thresholds()

            # Changed?
            if self.wanted_low_threshold != low_threshold:
                self.wanted_low_threshold = low_threshold
            if self.wanted_high_threshold != high_threshold:
                self.wanted_high_threshold = high_threshold

        # Is the currently wanted treshhold the same as the effective one?
        if self.low_threshold != self.wanted_low_threshold or \
                self.high_threshold != self.wanted_high_threshold:
            self.log.warn("%s thresholds are invalid (low: %d, high: %d). Restoring",
                    self, self.low_threshold , self.high_threshold)
            self.set_thresholds()

