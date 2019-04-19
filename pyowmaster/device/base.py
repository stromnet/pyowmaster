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
from pyownet.protocol import bytes2str, str2bytez
from time import time
import logging
from collections import namedtuple

from pyowmaster.event.events import OwConfigEvent

OwIoStatistic = namedtuple('OwIoStatistic', 'id operation uncached path time')
OwIoStatistic.OP_READ = 1
OwIoStatistic.OP_WRITE = 2
OwIoStatistic.OP_DIR = 3
OwIoStatistic.OPS = [0, 'read', 'write', 'dir']

DeviceId = namedtuple('DeviceId', 'id alias')


class Device(object):
    def __init__(self, ow, owid):
        self.type = type(self).__name__
        self.log = logging.getLogger(self.type)
        self.id = owid
        self.alias = None
        self.ow = ow

        # Initialize as present
        self.seen = False
        self.lost = False

    def config(self, config, is_initial):
        pass


class OwDevice(Device):
    def __init__(self, ow, owid):
        super(OwDevice, self).__init__(ow, owid)

        self.path = '/%s/' % self.id
        self.path_uncached = '/uncached/%s/' % self.id
        self.simultaneous = None
        self.device_id = None  # type: DeviceId

    def init(self, event_dispatcher, stats):
        self.event_dispatcher = event_dispatcher
        self.stats = stats

    def config(self, config, is_initial):
        """(Re-)Configure this device from config file.

        This looks for a device alias under either devices:<id>:alias, or if not there,
        falling back to devices:aliases:<id>"""
        self.alias = config.get(('devices', self.id, 'alias'), None)

        if not self.alias:
            self.alias = config.get(('devices', 'aliases', self.id), None)

        self.device_id = DeviceId(self.id, self.alias)

        self.max_exec_time = [
            None,
            config.get(('devices', (self.id, self.type), 'max_read_time'), 1),
            config.get(('devices', (self.id, self.type), 'max_write_time'), 1),
            config.get(('devices', (self.id, self.type), 'max_dir_time'), 2)
        ]

        self.custom_config(config, is_initial)

        self.emit_event(OwConfigEvent(time(), True))

    def custom_config(self, config, is_initial):
        """
        Custom device-specific config should be implemented in this method.

        When returned, a OwConfigEvent will be emited for the device.
        """
        pass

    def __getitem__(self, name_or_num):
        """
        If device supports channels, return channel identified by name_or_num.
        Matches on both name, ch #, and any channel alias.

        If device does not have channel support, return None.
        If channel not found, return False
        """
        if not name_or_num or not hasattr(self, 'channels'):
            return None

        # Lookup channel

        channel_list = self.channels
        if isinstance(self.channels, dict):
            if name_or_num in self.channels:
                return self.channels[name_or_num]

            channel_list = self.channels.values()

        for c in channel_list:
            if c.num == name_or_num or c.name == name_or_num or c.alias == name_or_num:
                return c

        return False

    def ow_read(self, sub_path, uncached=False):
        if not uncached:
            path = self.path
        else:
            path = self.path_uncached

        tS = time()
        raw = self.ow.read(path + sub_path)
        tE = time()

        self.store_io_statistics(OwIoStatistic(self.id, OwIoStatistic.OP_READ, uncached, sub_path, tE-tS))

        return raw

    def ow_write(self, sub_path, data):
        path = self.path

        if isinstance(data, str):
            data = str2bytez(data)
        elif isinstance(data, int):
            data = str2bytez(str(data))

        tS = time()
        raw = self.ow.write(path + sub_path, data)
        tE = time()

        self.store_io_statistics(OwIoStatistic(self.id, OwIoStatistic.OP_WRITE, False, sub_path, tE-tS))

        return data

    def ow_dir(self, sub_path='', uncached=False):
        if not uncached:
            path = self.path
        else:
            path = self.path_uncached

        tS = time()
        entries = self.ow.dir(path + sub_path)
        tE = time()

        self.store_io_statistics(OwIoStatistic(self.id, OwIoStatistic.OP_DIR, uncached, sub_path, tE-tS))

        return entries

    def ow_read_str(self, sub_path, uncached=False, strip=True):
        raw = self.ow_read(sub_path, uncached=uncached)

        data = bytes2str(raw)
        if strip:
            data = data.strip()

        return data

    def ow_read_int_list(self, sub_path, uncached=False):
        """Read a string path which contains comma separated integer values,
        and return a list of each value as an int"""
        raw = self.ow_read_str(sub_path, uncached=uncached)
        return list(map(int, map(str.strip, raw.split(','))))

    def emit_event(self, event, skip_device_id=False):
        if not event.device_id and not skip_device_id:
            event.device_id = self.device_id

        self.event_dispatcher.handle_event(event)

    def store_io_statistics(self, stats):
        # Keep last for external access
        self.last_io_stats = stats

        # Track
        self.stats.increment('ops.count_' + OwIoStatistic.OPS[stats.operation], stats.time*1000.0)
        self.stats.increment('ops.ms_' + OwIoStatistic.OPS[stats.operation], stats.time*1000.0)

        if stats.time > self.max_exec_time[stats.operation]:
            self.log.warning("%s: %s %s took %.2fs (max_exec_time %.2fs)",
                             stats.id, OwIoStatistic.OPS[stats.operation], stats.path, stats.time, self.max_exec_time[stats.operation])
        elif self.log.isEnabledFor(logging.DEBUG):
            self.log.debug("%s: %s %s took %.2fs (max_exec_time %.2fs)",
                           stats.id, OwIoStatistic.OPS[stats.operation], stats.path, stats.time, self.max_exec_time[stats.operation])

    def on_seen(self, timestamp):
        pass

    def on_alarm(self, timestamp):
        self.log.warning("%s: Unhandled alarm", str(self))

    def __str__(self):
        return "%s[%s]" % (self.__class__.__name__, self.device_id)


class OwBus(OwDevice):
    """Implements a Ow Bus as a OwDevice to keep some statistics and helpers."""
    def __init__(self, ow):
        super(OwBus, self).__init__(ow, '00.000000000000')
        self.path = "/"
        self.path_uncached = "/uncached/"

    def ow_dir_alarm(self, uncached=False):
        return self.ow_dir("alarm", uncached=uncached)

    def on_seen(self, timestamp):
        raise NotImplementedError("Not supposed to call on_seen on OwBus")

    def on_alarm(self, timestamp):
        raise NotImplementedError("Not supposed to call on_alarm on OwBus")


class OwChannel(object):
    """Represents some kind of channel on a 1Wire device
    Num is usually a 0-based index, while name may be the same, or an alternative such as 'A'
    """
    def __init__(self, num, name, cfg):
        """Create a new channel with num/name, and an cfg dict with channel-specific configuration"""
        self.num = num
        self.name = name
        self.alias = cfg.get('alias', None)

        # Keep cfg struct for others use, such as handlers
        self.config = cfg

    def __str__(self):
        alias = ""
        if self.alias:
            alias = " (alias %s)" % self.alias
        return "%s %s%s" % (self.__class__.__name__, self.name, alias)

    def get_event_types(self):
        """pywomaster.event.actionhandler uses this to determine which event types this channel may dispatch"""
        return ()

    def destroy(self):
        """Called on some devices when channel disappears"""
        pass
