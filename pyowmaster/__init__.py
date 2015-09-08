# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
"""pyowmaster implements a 1-Wire master, where the main focus is on providing low-latency input support"""

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

from __future__ import print_function
from pyownet.protocol import bytes2str,str2bytez,ConnError,OwnetError,ProtocolError
import device
from device.base import OwBus
from device.stats import OwStatistics, OwStatisticsEvent
from event.handler import OwEventDispatcher
import importlib
import time, re
import traceback
import logging
import prisched

__version__ = '0.0.0'
SCAN_FULL = 0
SCAN_ALARM = 1

class OwMaster(object):
    """Init a new OwMaster instance with the given pyownet OwnetProxy
    """
    def __init__(self, owNetProxy, config):
        self.log = logging.getLogger(type(self).__name__)
        self.ow = owNetProxy
        self.config = config

    def main(self):
        try:
            self._setup()
            self._mainloop()
        except:
            self.log.error("Unhandled exception, crashing", exc_info=True)

    def refresh_config(self, config):
        """This will ask all devices to refresh their config from the cfg struct"""
        self.config = config
        self.inventory.refresh_config(self.config)
        self.eventDispatcher.refresh_config(self.config)

    def _setup(self):
        # Create a scheduler where we queue our tasks
        self.scheduler = prisched.scheduler()

        # use two queues, prio order is always earlier created
        self.queueHighPrio = self.scheduler.createQueue().enter
        self.queueLowPrio = self.scheduler.createQueue().enter

        # Dispatcher for any events (counters, temp readings, switch changes etc)
        self.eventDispatcher = OwEventDispatcher()

        # Init our own statistics tracker
        self.stats = MasterStatistics(self.queueLowPrio, self.eventDispatcher,
                self.config.get('owmaster:stats_report_interval', 60))

        # Init bus object
        self.bus = OwBus(self.ow)
        self.bus.init(self.eventDispatcher, self.stats)
        self.bus.config(self.config)

        # Init pseudo-device fetching statistics from OWFS
        self.owstats = OwStatistics(self.ow)
        self.owstats.init(self.eventDispatcher, self.stats)
        self.owstats.config(self.config)

        # Init a factory, and then an associated inventory
        self.factory = DeviceFactory(self.ow, self.eventDispatcher, self.stats, self.config)
        self.inventory = DeviceInventory(self.factory, self.config)

        # Load handler modules
        self.load_handlers()

        # Key'ed SCAN_FULL(0) and SCAN_ALARM(1)
        self.lastScan = [0, 0]
        self.scanInterval = [
                self.config.get('owmaster:scan_interval', 30),
                self.config.get('owmaster:alarm_scan_interval', 1.0)
            ]
        self.scanQueue = [self.queueLowPrio, self.queueHighPrio]

        self.scanConnErrs = 0

        self.log.debug("Configured for scanning every %.2fs, alarm scanning every %.1fs",
                self.scanInterval[SCAN_FULL],
                self.scanInterval[SCAN_ALARM])

    def _mainloop(self):
        self.simultaneousTemperaturePending = False

        # These initial scans will enqueue jobs to the scheduler
        self.scan(SCAN_FULL)
        self.scan(SCAN_ALARM)

        while True:
            try:
                self.scheduler.run()
                # No more jobs
                break
            except KeyboardInterrupt:
                self.log.info("Exiting")
                break
            except OwnetError, e:
                self.log.error("Unhandled OwnetError: %s", e, exc_info=True)
            except ProtocolError, e:
                self.log.error("Unhandled ProtocolError: %s", e, exc_info=True)
            except ConnError, e:
                self.log.error("Unhandled ConnError: %s", e, exc_info=False)


    def shutdown(self):
        """Shutdown all background operations, if any"""
        try:
            self.eventDispatcher.shutdown()
        except:
            self.log.error("Unhandled exception while shutting down event handlers", exc_info=True)

    def load_handlers(self):
        modules = self.config.get('modules', {})
        if len(modules) == 0:
            return

        for module_name in modules.keys():
            self.log.debug("Initing module %s", module_name)
            m = importlib.import_module(module_name)

            # Create and execute initial config
            h = m.create(self.inventory)
            try:
                h._init_config(self.config, module_name)

                # Add to eventDispatcher; this handler will now get all events
                self.eventDispatcher.add_handler(h)
            except:
                try:
                    h.shutdown()
                except:
                    pass
                raise


    def scan(self, scan_mode):
        backoff = 0
        try:
            self._scan(scan_mode == SCAN_ALARM)
            self.lastScan[scan_mode] = time.time()
            if self.scanConnErrs > 0:
                self.log.info("Connection back online")

            self.scanConnErrs = 0

            # In normal cases, try to read stats every normal scan
            # This is done outside of scan method, in case bus scan fails for
            # other reasons (but still returns OK; possible)
            if scan_mode != SCAN_ALARM:
                # Read bus statistics through pseudo-devoce
                self.owstats.on_seen(time.time())

        except ConnError, e:
            self.scanConnErrs+=1
            backoff = min((self.scanConnErrs * 2) + 1, 20)
            self.log.error("Connection error while executing main loop. Waiting %ds and retrying", backoff)
        finally:
            self.scanQueue[scan_mode](self.scanInterval[scan_mode] + backoff, self.scan, [scan_mode])


    def _scan(self, alarmMode):
        try:
            if alarmMode:
                self.stats.increment('tries.alarm_scan')
                ids = self.bus.owDirAlarm(uncached=True)
            else:
                self.stats.increment('tries.full_scan')
                ids = self.bus.owDir(uncached=True)
        except OwnetError, e:
            self.log.error("Bus scan failed: %s",e)
            return

        timestamp = time.time()
#        self.log.debug("%s scan executed in %.2fms", \
#                "Alarm" if alarmMode else "Bus", self.bus.lastIoStats.time*1000)

        deviceList = []
        uniqueDevices = set()
        for devId in ids:
            if devId in uniqueDevices:
                self.log.warn("Duplicate device ID in scan: %s" % devId)
                self.stats.increment('error.scan_duplicate')
                continue

            uniqueDevices.add(devId)

            # Finds existing device or creates new, if family is known
            dev = self.inventory.find(devId, create=True)
            if dev == None:
                continue

            deviceList.append(dev)

        if not alarmMode:
            # Find "lost" devices
            missing = self.inventory.list(skipList = deviceList)
            if missing:
                self.log.warn("Missing %d (of %d) devices: %s", len(missing), self.inventory.size(), ', '.join(map(str,missing)))
                self.stats.increment('error.lost_devices', len(missing))

            # TODO: Handle some way
        else:
            self.stats.increment('bus.device_count', len(deviceList))

        simultaneous = {}
        for dev in deviceList:
            if alarmMode:
                # Schedule Alarm handler immediately
                self.queueHighPrio(0, dev.on_alarm, [timestamp])
            else:
                self.queueLowPrio(0, dev.on_seen, [timestamp])
                if dev.simultaneous != None:
                    # Device supports simultaneous handling, enqueue it
                    if not simultaneous.has_key(dev.simultaneous):
                        simultaneous[dev.simultaneous] = []

                    simultaneous[dev.simultaneous].append(dev)

        # Process any simultaneous requests
        if len(simultaneous.keys()) != 0:
            # Simultaneous temperature conversions?
            if simultaneous.has_key('temperature'):
                devs = simultaneous.pop('temperature')
                self.simultaneousTemperature(devs)

            # Fail any unhandled variants
            if len(simultaneous.keys()) != 0:
                raise Exception("Unhandled simultaneous keys: %s" % str(simultaneous))

        # End of scan method

    def simultaneousTemperature(self, devices):
        """
        Executes a simultanous temperature conversion, scheduling read of all devices after
        the conversions is estimated to be finished.

        If the bus is fully powered, we can start a simultaneous temperature conversion,
        and then do other operations inbetween. As long as all sensors are powered, we
        should have no problem with this.

        If any device is NOT powered, it will execute a regular convert right befor reading.
        """
        if self.simultaneousTemperaturePending:
            raise Exception("Simultanous temperature convert already pending")
#            self.log.warn("Skipping simultanous temperature; already pending")
#            return

        self.simultaneousTemperaturePending = True

        # Execute conversion. this returns immediately
        self.bus.owWrite('simultaneous/temperature', '1')
        convert_start_ts = time.time()
        self.simultaneousTemperaturePending = time.time()
        self.log.debug("Simultaneous temperature executed in %.2fms", self.bus.lastIoStats.time*1000)

        # Wait 1000ms before actually reading the scratchpads
        self.queueLowPrio(1.0, self._simultaneousTemperatureRead, [devices, convert_start_ts])

    def _simultaneousTemperatureRead(self, devices, convert_start_ts):
        """Reads a list of temperature sensors after simultaneous conversion is estimated to have finished"""
        self.log.debug("Simultaneous temperature convert ready, reading")
        self.simultaneousTemperaturePending = False
        for dev in devices:
            self.queueLowPrio(0, dev.read_temperature, [convert_start_ts])




class DeviceFactory(object):
    def __init__(self, owNetProxy, eventDispatcher, stats, config):
        self.log = logging.getLogger(type(self).__name__)
        self.ow = owNetProxy
        self.deviceTypes = {}
        self.eventDispatcher = eventDispatcher
        self.stats = stats
        self.config = config

        # Register known device classes
        for d in device.__all__:
            m = importlib.import_module('pyowmaster.device.'+d)
            m.register(self)

    def register(self, familyCode, classRef):
        assert self.deviceTypes.get(familyCode) == None, "Family code %s already registered" % familyCode
        self.deviceTypes[familyCode] = classRef

    def create(self, dev_id):
        family = dev_id[0:2]
        devType = self.deviceTypes.get(family)
        if devType == None:
            self.log.info("Cannot create device with family code %s, not registered", family)
            return None

        dev = devType(self.ow, dev_id)
        dev.init(self.eventDispatcher, self.stats)

        try:
            dev.config(self.config)
        except OwnetError as e:
            self.log.warn("Failed to configure %s, OW failure: %s",
                    dev_id, e)

        return dev


class DeviceInventory(object):
    def __init__(self, factory, config):
        self.log = logging.getLogger(type(self).__name__)
        self.devices = {}
        self.aliases = {}
        self.factory = factory

        self.refresh_config(config)

    def refresh_config(self, root_config):
        """Init/refresh device configurations.

        This will create any devices in config, and tries to configure them.
        For all pre-existing devices (on config refresh), it will ask each
        device to refresh their config.

        Alias mappings will be updated here too.
        """
        configured_ids = set()
        # Load from devices section
        for dev_id in root_config.get('devices', {}):
            configured_ids.add(dev_id)

        # Load from common aliases-section too
        for dev_id in root_config.get('devices:aliases', {}):
            configured_ids.add(dev_id)

        # Reset aliases map, re-add freshly to avoid the mess of
        # cleaning up stale ones if they are changed
        self.aliases = {}

        # Create devices
        just_created = set()
        for dev_id in configured_ids:
            # May contain non-IDs too, such as common settings per device-type, or
            # aliases section.
            try:
                if not RE_DEV_ID.match(dev_id):
                    continue
            except TypeError as e:
                raise ConfigurationError("Invalid device ID %s: %s" % (dev_id, e))

            # Only create devices which are not yet known
            if dev_id not in self.devices:
                self._create_device(dev_id)
                just_created.add(dev_id)

        # Now, configure all existing devices
        for dev_id in self.devices:
            dev = self.devices[dev_id]
            if not dev:
                # Unknown device type
                continue

            if dev_id in just_created:
                # Was just created, and thus configured
                continue

            try:
                dev.config(root_config)
            except OwnetError as e:
                # This may occur if a device config requires online device,
                # but failed to find it, or if it failed to configure the remote device.
                # It should try later!
                self.log.warn("Failed to configure %s, OW failure: %s",
                        dev, e)
            except OwMasterException:
                self.log.error("Failed to configure device %s",
                        dev, exc_info=True)

            if dev.alias:
                self._add_alias(dev.alias, dev_id)

    def find(self, idOrPath, create=False):
        """Find a Device object associated with the specified 1-wire ID.

        As the name indicates, a plain ID can be given, or a path which contains an ID.
        If the devices is not found, it is created.
        """
        dev_id = idFromPath(idOrPath)
        if not dev_id:
            # Invalid ID, could be an alias
            # XXX: If any device has an alias, we will miss it.
            # There is a bug in OWFS, it returns aliased names even if we ask it not to:
            # https://sourceforge.net/p/owfs/bugs/60/
            # Until fixed, do not use alias.
            return None

        dev = self.devices.get(dev_id)
        if dev == None:
            if not create:
                return None

            dev = self._create_device(dev_id)

        if dev == False:
            # But always return None..
            return None

        return dev

    def _create_device(self, dev_id):
        """Internal function to create a device

        The created device is put in the internal devices dict, and the device
        is then returned.

        If the DeviceFactory cannot create a device of the given ID,
        we use the value False to indicate a non-supported entry.
        """
        dev = self.factory.create(dev_id)

        if dev == None:
            # Not supported. Store False in dict
            dev = False
        else:
            self.log.info("New device %s", dev)
            if dev.alias:
                self._add_alias(dev.alias, dev_id)

        self.devices[dev_id] = dev

    def _add_alias(self, alias, dev_id):
        """Add a device alias to the aliases mapping.

        If the device is already mapped, a duplicate warning is emitted.
        """
        if alias in self.aliases:
            if self.aliases[alias] == dev_id:
                return

            self.log.warn("Duplicate alias %s, seen on device %s and device %s",
                    alias, dev_id, self.aliases[alias])

        self.aliases[alias] = dev_id

    def find_alias(self, alias_or_id):
        """Find an existing Device object by 1-wire ID OR alias"""
        device = self.devices.get(alias_or_id, None)
        if device:
            return device

        devId = self.aliases.get(alias_or_id, None)
        if not devId:
            return None

        device = self.devices.get(devId, None)
        if not device:
            raise Exception("Alias %s pointed to device %s which was not found" % (alias_or_id, devId))

        return device

    def list(self, skipList=None):
        """Return a list of all known devices.

        If skipList is set, we skip all devices in that list"""
        out = []
        skip = {}
        if skipList:
            # Transform to map with ID as key
            for dev in skipList:
                if type(dev) != str:
                    dev = dev.id
                skip[dev] = 1

        for dev_id in self.devices:
            dev = self.devices[dev_id]
            if dev and dev_id not in skip:
                out.append(dev)

        return out

    def __iter__(self):
        return self.devices.values().__iter__()

    def size(self):
        return len(self.devices)


class MasterStatistics:
    def __init__(self, queue, eventDispatcher, reportInterval=60):
        self.log = logging.getLogger(type(self).__name__)
        self.counters = {}
        self.queue = queue
        self.eventDispatcher = eventDispatcher
        self.reportInterval = reportInterval
        self.queue(self.reportInterval, self.report)

    def init(self, key):
        """Initialize a counter key to be reported even if no increment is ever made.

        Init is not necessary, but if .increment is never called, it will never
        be reported if not inited.
        """
        self.increment(key, 0)

    def increment(self, key, value=1):
        """Increment a statistics counter by 1, or more.

        The key shall be in the format "<counter>.<key>", and if has not been
        used before it will be pre-inited to 0 before incrementing it.
        """
        if key not in self.counters:
            if '.' not in key:
                raise Error("Statistics key should have the format <category>.<name>")

            self.counters[key] = 0

#        self.log.debug("Incrementing %s with %.3f", key, value)
        self.counters[key] += value

    def report(self):
        """Report all tracked values"""
        self.log.debug("Reporting statistics")
        timestamp = time.time()
        for key in self.counters:
            (category, name) = key.split('.')
            value = self.counters[key]

            ev = OwStatisticsEvent(timestamp, category, name, value)
            self.eventDispatcher.handle_event(ev)

        self.queue(self.reportInterval, self.report)


RE_DEV_ID = re.compile('([A-F0-9][A-F0-9]\.[A-F0-9]{12})')
def idFromPath(idOrPath):
    """Tries to interpret an 1-Wire ID from a path string"""
    # Ignore non-ID names (such as aliases)
    m = RE_DEV_ID.search(idOrPath)
    if not m:
        return None

    return str(m.group(1))

