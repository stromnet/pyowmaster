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

class OwEventBase(object):
    """Base object for any events sent emitted from
    1-Wire devices as result of alarms or regular polling"""
    def __init__(self, timestamp):
        self.timestamp = timestamp
        self.deviceId = None

    def __str__(self):
        return "OwEvent[%d: %s, unknown]" % (self.timestamp, self.deviceId)

class OwCounterEvent(OwEventBase):
    """Describes an counter reading"""
    def __init__(self, timestamp, channel, value):
        super(OwCounterEvent, self).__init__(timestamp)
        self.channel = channel
        self.value = value

    def __str__(self):
        return "OwCounterEvent[%d: %s, ch %s, %d]" % (self.timestamp, self.deviceId, self.channel, self.value)

class OwTemperatureEvent(OwEventBase):
    """Describes an temperature reading"""
    def __init__(self, timestamp, value, unit):
        super(OwTemperatureEvent, self).__init__(timestamp)
        self.value = value
        self.unit = unit

    def __str__(self):
        return "OwTemperatureEvent[%s, %.2f %s]" % (self.deviceId, self.value, self.unit)

class OwSwitchEvent(OwEventBase):
    """Describes an event which has occured on the specified OwDevice ID/channel.

    For momentary inputs, the value is always TRIGGED
    For toggle inputs, and outputs, the value is either ON or OFF.

    The channel identifier is device specific, but is generally 'A' or 'B', or a numeric.
    """
    OFF = "OFF"
    ON = "ON"
    TRIGGED = "TRIGGED"

    def __init__(self, timestamp, channel, value):
        super(OwSwitchEvent, self).__init__(timestamp)
        self.channel = channel
        self.value = value

    def __str__(self):
        return "OwSwitchEvent[%d, %s, ch %s, %s]" % (self.timestamp, self.deviceId, self.channel, self.value)



