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
import collections, logging
import importlib, inspect

from pyowmaster.event.handler import ThreadedOwEventHandler
from pyowmaster.event.events import *
from pyowmaster.event.action import EventAction
from pyowmaster.exception import *

def create(inventory):
    return ActionEventHandler(inventory)

class ActionEventHandler(ThreadedOwEventHandler):
    """A EventHandler which reacts to events and executes actions based on these"""
    def __init__(self, inventory, max_queue_size=0):
        super(ActionEventHandler, self).__init__(max_queue_size)

        self.action_factory = ActionFactory(inventory)
        self.inventory = inventory
        self.event_handlers_by_dev = {}
        self.start()

    def config(self, module_config, root_config):
        failures = 0

        # Do we have any action modules to pre-load/configure?
        for module in module_config.get('action_modules', []):
            try:
                self.action_factory.load_by_module(module)
            except:
                self.log.error("Failed to init action module '%s'", module, exc_info=True)
                failures = failures + 1

        # Iterate all configured devices, find any event actions
        # These are stored in a 3-level dict, device->channel->event-type->[actions...]
        event_handlers_by_dev = {}

        for dev in self.inventory:
            # Only handle devices with a "channels" list
            if not hasattr(dev, 'channels'):
                continue

            by_ch  = None
            channel_list = dev.channels

            # Some devices has a dict with name->channel
            if isinstance(dev.channels, dict):
                channel_list = dev.channels.values()

            for ch in channel_list:
                by_type = None

                # Find any configuration for each of the event types this channel may dispatch
                self.log.debug("%s ch %s can do %s", dev, ch, ch.get_event_types())
                for event_type in ch.get_event_types():
                    # True/false is used since YAML converts 'on' to True, 'off' to False
                    event_type_key = event_type
                    if event_type == 'on': event_type_key = True
                    if event_type == 'off': event_type_key = False
                    if not event_type_key in ch.config:
                        continue

                    # Ch configuration can have a sub-entry for each event type
                    # These values can in turn be either a single dict with action,
                    # or a list of dicts with action
                    actions_for_type = ch.config[event_type_key]
                    if actions_for_type is None:
                        continue

                    # Init storage
                    if not by_ch:
                        by_ch = event_handlers_by_dev[dev.id] = {}
                    if not by_type:
                        by_type = by_ch[ch.name] = {}
                    event_actions = by_type[event_type] = []

                    # Normalize actions_for_type to list, if it is a single entry only
                    if isinstance(actions_for_type, collections.Mapping):
                        actions_for_type = [actions_for_type]

                    for action_cfg in actions_for_type:
                        try:
                            a = self.action_factory.create(dev, ch, event_type, action_cfg)
                            event_actions.append(a)

                            self.log.info("Adding action for %s ch %s, when %s do %s",
                                    dev.id, ch, event_type, a)

                        except OwMasterException as e:
                            self.log.error("Failed to init '%s' action on device %s ch %s (%s): %s",
                                    event_type, dev.id, ch.name, action_cfg, e.message, exc_info=True)

                            failures = failures + 1

        # All created, replace active cfg
        self.event_handlers_by_dev = event_handlers_by_dev

        if failures > 0:
            self.log.warn("One or more error(s) occured during action initialization")

    def handle_event_blocking(self, event):
        # XXX: Only PIO events
        if not isinstance(event, OwPIOEvent):
            return

        try:
            by_ch = self.event_handlers_by_dev[event.device_id.id]
            by_type = by_ch[event.channel]
            actions = by_type[event.value.lower()]
        except KeyError:
            #self.log.debug("No handler found for event %s", event)
            return

        for action in actions:
            try:
                action.handle_event(event)
            except:
                self.log.error("Failed to execute action %s", str(action), exc_info=True)

class ActionFactory(object):
    """Factory to create Action instances based on a action_config entry"""
    def __init__(self, inventory):
        self.log = logging.getLogger(type(self).__name__)
        self.action_modules = {}
        self.inventory = inventory

    def create(self, dev, channel, event_type, action_config):
        """Parse an action config dict and create a new action instance for the
        defined dev/ch/event type.

        The action config can either be a dict with
            action: <name of action module/fn>
            <optional options>: <...>

        or a dict with a single key:
            <name of action module/fn>: <single value>

        The action module name may contain a dot, in which case it identifies a
        method of the action module. For example,

            setpio.on: 12.1212121212.A

        will tell the 'pio' module to run action 'on' for the specified device.
        """
        if len(action_config) == 1 and 'action' not in action_config:
            action_target = action_config.keys()[0]
            single_value = action_config.values()[0]
        else:
            action_target = action_config.get('action', None)
            single_value = None

        if not action_target or type(action_target) is not str:
            raise ConfigurationError("Action config must be either single-key dict, or have 'action' key with a string value")

        # Split action_target name into module and method (optionally multiple)
        action_target = action_target.split('.')
        action_module = action_target[0]
        action_method = action_target[1:]

        class_ref = self.get_action_module(action_module)
        a = class_ref(self.inventory, dev, channel, event_type, action_method, action_config, single_value)
        return a

    def get_action_module(self, action_module):
        if action_module not in self.action_modules:
            self.load_by_module(action_module)

            if action_module not in self.action_modules:
                raise ConfigurationError("Unknown action module '%s', package found but not imported?" % action_module)

        return self.action_modules[action_module]

    def load_by_module(self, name):
        self.log.debug("Loading module %s", name)
        try:
            m = importlib.import_module(name)
            self.scan_module(m)
        except ImportError:
            try:
                # Try builtin package
                m = importlib.import_module('.'+name, 'pyowmaster.event.action')
                self.scan_module(m)
            except ImportError:
                raise ConfigurationError("Unknown action module '%s', not found" % name)

    def scan_module(self, m):
        self.log.debug("Scanning module %s", m)
        # Search for any EventAction classes
        for name, obj in inspect.getmembers(m, inspect.isclass):
            if obj == EventAction:
                continue

            for parent in inspect.getmro(obj):
                if parent != EventAction:
                    continue

                if hasattr(obj, 'action_alias'):
                    name = obj.action_module_name
                else:
                    # Use last part of module name
                    name = obj.__module__.split('.')[-1]

                self.log.debug("Registering action module %s => %s (module %s)",
                        name, obj, obj.__module__)

                self.register(name, obj)
                break

    def register(self, name, class_ref):
        if self.action_modules.get(name) == class_ref:
            return
        assert self.action_modules.get(name) == None, "Action %s already registered with %s" % (name, class_ref)
        self.action_modules[name] = class_ref


