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

from base import OwDevice, DeviceId
from ..event.events import OwStatisticsEvent

ERRORS = ("BUS_bit_errors", "BUS_byte_errors", "BUS_detect_errors",
    "BUS_echo_errors", "BUS_level_errors", "BUS_next_alarm_errors",
    "BUS_next_errors", "BUS_readin_data_errors", "BUS_status_errors",
    "BUS_tcsetattr_errors",
    "CRC16_errors", "CRC8_errors", 
    "DS2480_level_docheck_errors", "DS2480_read_fd_isset",
    "DS2480_read_null", "DS2480_read_read",
    "NET_accept_errors", "NET_connection_errors", "NET_read_errors")

TRIES = ("CRC16_tries", "CRC8_tries", "read_tries")

class OwStatistics(OwDevice):
    """Implements a pseudo device which fetches statistics"""
    def __init__(self, ow):
        super(OwStatistics, self).__init__(ow, None)
        self.path = "/statistics/"
        self.pathUncached = "/uncached/statistics/"
        self.deviceId = DeviceId(None, 'OwStatistics')

    def on_seen(self, timestamp):
        """Read all error known counters"""
        for e in ERRORS:
            path = "errors/%s" % e
            data = self.owRead(path)
            value = int(data)

            ev = OwStatisticsEvent(timestamp, OwStatisticsEvent.CATEOGORY_ERROR, e, value)
            ev.deviceId = DeviceId(None, ev.name)
            self.emitEvent(ev)

        for e in TRIES:
            if e == 'read_tries':
                path = "read/tries.ALL"
            else:
                # XXX: Yes, CRC16_tries and CRC8_tries is under errors..
                path = "errors/%s" % e

            data = self.owRead(path)
            if e == 'read_tries':
                read_tries = data.split(',')
                for n in range(0, len(read_tries)):
                    value = int(read_tries[n])

                    ev = OwStatisticsEvent(timestamp, OwStatisticsEvent.CATEOGORY_TRIES, '%s_%d' % (e, n+1), value)
                    ev.deviceId = DeviceId(None, ev.name)
                    self.emitEvent(ev)

            else:
                value = int(data)
                ev = OwStatisticsEvent(timestamp, OwStatisticsEvent.CATEOGORY_TRIES, e, value)
                ev.deviceId = DeviceId(None, ev.name)
                self.emitEvent(ev)
