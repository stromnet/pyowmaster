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

class OwEventBase(object):
    """Base object for any events sent emitted from
    1-Wire devices as result of alarms or regular polling"""
    def __init__(self, timestamp, is_reset):
        self.timestamp = timestamp
        self.device_id = None
        self.is_reset = is_reset

    def __str__(self):
        return "OwEvent[%d: %s, unknown]" % (self.timestamp, self.device_id)

class OwCounterEvent(OwEventBase):
    """Describes an counter reading"""
    def __init__(self, timestamp, channel, value, is_reset=False):
        super(OwCounterEvent, self).__init__(timestamp, is_reset)
        self.channel = channel
        self.value = value

    def __str__(self):
        return "OwCounterEvent[%d: %s, ch %s, %d]" % (self.timestamp, self.device_id, self.channel, self.value)

class OwTemperatureEvent(OwEventBase):
    """Describes an temperature reading"""
    def __init__(self, timestamp, value, unit, is_reset=False):
        super(OwTemperatureEvent, self).__init__(timestamp, is_reset)
        self.value = value
        self.unit = unit

    def __str__(self):
        return "OwTemperatureEvent[%d: %s, %.2f %s]" % (self.timestamp, self.device_id, self.value, self.unit)

class OwStatisticsEvent(OwEventBase):
    CATEOGORY_ERROR = "error"
    CATEOGORY_TRIES = "tries"
    """Describes an statistics reading"""
    def __init__(self, timestamp, category, name, value, is_reset=False):
        super(OwStatisticsEvent, self).__init__(timestamp, is_reset)
        self.name = name
        self.category = category
        self.value = value

    def __str__(self):
        return "OwStatisticsEvent[%d: %s %s, %d]" % (self.timestamp, self.category, self.name, self.value)

class OwPIOEvent(OwEventBase):
    """Describes an event which has occured on the specified OwDevice ID/channel.

    For momentary inputs, the value is always TRIGGED
    For toggle inputs, and outputs, the value is either ON or OFF.

    The channel should be a OwPIOChannel instance

    The is_reset value may be set to True of this was dispatched due to a device
    reset or application startup state detection (applicable for toggle inputs or
    outputs only).
    """
    OFF = "OFF"
    ON = "ON"
    TRIGGED = "TRIGGED"

    def __init__(self, timestamp, channel, value, is_reset=False):
        super(OwPIOEvent, self).__init__(timestamp, is_reset)
        self.channel = channel
        self.value = value

    def __str__(self):
        return "OwPIOEvent[%d, %s, %s, %s%s]" % (self.timestamp, self.device_id, self.channel, self.value, " (reset)" if self.is_reset else "")



