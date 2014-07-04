"""python ownet master"""
# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :


#
# Copyright 2014 Johan Ström
#

from __future__ import print_function
from pyownet.protocol import bytes2str,str2bytez,ConnError,OwnetError
import device
from device.base import OwBus
from event.handler import OwEventDispatcher
import importlib
import time, re
import traceback
import logging
import prisched

__version__ = '0.0.0'

class OwMaster(object):
    """Init a new OwMaster instance with the given pyownet OwnetProxy
    """
    def __init__(self, owNetProxy, config_get):
        self.log = logging.getLogger(type(self).__name__)
        self.ow = owNetProxy
        self.config_get = config_get

    def main(self):
        try:
            self._setup()
            self._mainloop()
        except:
            self.log.error("Unhandled exception, crashing", exc_info=True)

    def _setup(self):
        # Create a scheduler where we queue our tasks
        self.scheduler = prisched.scheduler()
        
        # use two queues, prio order is always earlier created
        self.queueHighPrio = self.scheduler.createQueue().enter
        self.queueLowPrio = self.scheduler.createQueue().enter

        # Init bus object, event dispatcher
        self.bus = OwBus(self.ow)
        self.eventDispatcher = OwEventDispatcher()

        # Init a factory, and then an associated inventory
        self.factory = DeviceFactory(self.ow, self.eventDispatcher, self.config_get)
        self.inventory = DeviceInventory(self.factory, self.config_get)

        self.lastFullScan = 0
        self.lastAlarmScan = 0

        self.fullScanInterval = self.config_get('owmaster', 'scan_interval', 30)
        self.alarmScanInterval = self.config_get('owmaster', 'alarm_scan_interval', 1.0)

        self.log.debug("Configured for scanning every %.2fs, alarm scanning every %.1fs",\
                self.fullScanInterval,\
                self.alarmScanInterval)

    def _mainloop(self):
        self.simultaneousTemperaturePending = False

        # These initial scans will enqueue jobs to the scheduler
        self.scanFull()
        self.scanAlarm()

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


    def shutdown(self):
        """Shutdown all background operations, if any"""
        try:
            self.eventDispatcher.shutdown()
        except:
            self.log.error("Unhandled exception while shutting down event handlers", exc_info=True)

    def scanFull(self):
        try:
            self.scan(False)
            self.lastFullScan = time.time()
        except ConnError, e:
            self.log.error("Connection error while executing main loop. Waiting and retrying", exc_info=True)

        self.queueLowPrio(self.fullScanInterval, self.scanFull, [])

    def scanAlarm(self):
        try:
            self.scan(True)
            self.lastAlarmScan = time.time()
        except ConnError, e:
            self.log.error("Connection error while executing main loop. Waiting and retrying", exc_info=True)

        self.queueHighPrio(self.alarmScanInterval, self.scanAlarm, [])

    def scan(self, alarmMode):
        try:
            if alarmMode:
                ids = self.bus.owDirAlarm(uncached=True)
            else:
                ids = self.bus.owDir(uncached=True)
        except OwnetError, e:
            self.log.error("Bus scan failed: %s",e)
            return 

        timestamp = time.time()
#        self.log.debug("%s scan executed in %.2fms", \
#                "Alarm" if alarmMode else "Bus", self.bus.lastIoStats.time*1000)

        deviceList = []
        for devId in ids:
            # Finds existing device or creates new, if family is known
            dev = self.inventory.find(devId)
            if dev == None:
                continue

            deviceList.append(dev)

        if not alarmMode:
            # Find "lost" devices
            missing = self.inventory.list(skipList = deviceList)
            if missing:
                self.log.warn("Missing devices: %s", ', '.join(map(str,missing)))
            # TODO: Handle some way

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
                raise Error("Unhandled simultaneous keys: %s" % str(simultaneous))

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
            self.log.debug("Skipping simultanous temperature; already pending")
            return

        self.simultaneousTemperaturePending = True

        # Execute conversion. this returns immediately
        self.bus.owWrite('simultaneous/temperature', '1')
        self.simultaneousTemperaturePending = time.time()
        self.log.debug("Simultaneous temperature executed in %.2fms", self.bus.lastIoStats.time*1000)

        # Wait 1000ms before actually reading the scratchpads
        self.queueLowPrio(1.0, self._simultaneousTemperatureRead, [devices])

    def _simultaneousTemperatureRead(self, devices):
        """Reads a list of temperature sensors after simultaneous conversion is estimated to have finished"""
        self.log.debug("Simult ready, reading")
        timestamp = self.simultaneousTemperaturePending
        self.simultaneousTemperaturePending = False
        for dev in devices:
            self.queueLowPrio(0, dev.read_temperature, [timestamp])




class DeviceFactory(object):
    def __init__(self, owNetProxy, eventDispatcher, config_get):
        self.log = logging.getLogger(type(self).__name__)
        self.ow = owNetProxy
        self.deviceTypes = {}
        self.eventDispatcher = eventDispatcher
        self.config_get = config_get

        # Register known device classes
        for d in device.__all__:
            m = importlib.import_module('pyowmaster.device.'+d)
            m.register(self)

    def register(self, familyCode, classRef):
        assert self.deviceTypes.get(familyCode) == None, "Family code %s already registered" % familyCode
        self.deviceTypes[familyCode] = classRef

    def create(self, id):
        family = id[0:2]
        devType = self.deviceTypes.get(family)
        if devType == None:
            self.log.info("Cannot create device with family code %s, not registered", family)
            return None

        dev = devType(self.ow, id)
        dev.init(self.eventDispatcher)
        dev.config(self.config_get)
        return dev


class DeviceInventory(object):
    def __init__(self, factory, config_get):
        self.log = logging.getLogger(type(self).__name__)
        self.devices = {}
        self.factory = factory

    """Find a Device object associated with the specified 1-wire ID.
    
    As the name indicates, a plain ID can be given, or a path which contains an ID.
    If the devices is not found, it is created.
    """
    def find(self, idOrPath):
        id = idFromPath(idOrPath)
        if not id:
            # Invalid ID, could be an alias
            # XXX: If any device has an alias, we will miss it. 
            # There is a bug in OWFS, it returns aliased names even if we ask it not to:
            # https://sourceforge.net/p/owfs/bugs/60/
            # Until fixed, do not use alias.
            return None

        device = self.devices.get(id)
        if device == None:
            device = self.factory.create(id)
            if device == None:
                # Not supported. Store False in dict
                device = False
            else:
                self.log.info("New device %s (%s)", id, device)

            self.devices[id] = device

        if device == False:
            # But always return None..
            return None

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

        for id in self.devices:
            dev = self.devices[id]
            if dev and id not in skip:
                out.append(dev)

        return out



RE_DEV_ID = re.compile('([A-F0-9][A-F0-9]\.[A-F0-9]{12})')
def idFromPath(idOrPath):
    """Tries to interpret an 1-Wire ID from a path string"""
    # Ignore non-ID names (such as aliases)
    m = RE_DEV_ID.search(idOrPath)
    if not m:
        return None

    return str(m.group(1))


    
def selftest():
    assert idFromPath('10.CB310B000800') == '10.CB310B000800'
    assert idFromPath('/10.CB310B000800') == '10.CB310B000800'
    assert idFromPath('/uncached/10.CB310B000800') == '10.CB310B000800'
    assert idFromPath('/uncached/10.CB310B000800/temperature') == '10.CB310B000800'
    assert idFromPath('/uncached/alarm/10.CB310B000800') == '10.CB310B000800'

selftest()

