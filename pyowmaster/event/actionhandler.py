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
import time

from pyowmaster.event.handler import ThreadedOwEventHandler
from pyowmaster.event.events import *
from pyowmaster.event.action import EventAction
from pyowmaster.event.action.conditionals import parse_conditional, init_jinja2
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
        self.jinja_env = init_jinja2()
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

            by_ch = None
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
                    if event_type_key not in ch.config:
                        continue

                    # Ch configuration can have a sub-entry for each event type
                    # These values can in turn be either a list of dicts with actions,
                    # or a dict with 'when' and 'actions' keys, where the list of actions
                    # is held under 'actions'.
                    action_cfg_for_type = ch.config[event_type_key]
                    if action_cfg_for_type is None:
                        continue

                    # Normalize action_cfg_for_type to dict, if it just a list
                    if isinstance(action_cfg_for_type, collections.abc.Sequence):
                        # typically a list of actions
                        action_cfg_for_type = dict(actions=action_cfg_for_type)

                    if 'actions' not in action_cfg_for_type:
                        self.log.error('expected dict with "actions" key at device %s ch %s event %s',
                                dev, ch, event_type)
                        failures += 1
                        continue

                    # Init storage
                    if not by_ch:
                        by_ch = event_handlers_by_dev[dev.id] = {}
                    if not by_type:
                        by_type = by_ch[ch.name] = {}

                    # For each configured event, this "event config" holds details of it
                    when_condition = action_cfg_for_type.get('when', None)
                    event_actions = []
                    by_type[event_type] = dict(
                        # If a conditional was set for the event (not individual actions)
                        when=when_condition,
                        conditional=parse_conditional(when_condition, self.jinja_env),
                        # When the event last occurred
                        last_occurred=None,
                        # When the event last was executed (i.e. not stopped by shared conditional)
                        # Note that each individual event may still have been blocked.
                        last_ran=None,
                        # Which actions to execute
                        actions=event_actions
                    )

                    # Try to load each configured action
                    for action_cfg in action_cfg_for_type['actions']:
                        try:
                            a = self.action_factory.create(dev, ch, event_type, action_cfg)
                            a.init_conditional(action_cfg, self.jinja_env)
                            event_actions.append(a)

                            self.log.info("Adding action for %s ch %s, when %s do %s",
                                    dev.id, ch, event_type, a)

                        except OwMasterException as e:
                            self.log.error("Failed to init '%s' action on device %s ch %s (%s): %s",
                                    event_type, dev.id, ch.name, action_cfg, e.message, exc_info=True)

                            failures += 1

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
            event_type = event.value.lower()
            event_cfg = by_type[event_type]
        except KeyError:
            #self.log.debug("No handler found for event %s", event)
            return

        actions = event_cfg['actions']
        conditional = event_cfg['conditional']

        # Create a Jinja context which is used for evaluating conditionals.
        # It allows addressing devices either by alias (as a variable name), or by ID via a
        # devices['12.2322id'] map.
        # Direct access by ID is not possible, since jinja variable names does not
        # allow leading digit.
        devices = {}
        devices.update(self.inventory.devices)
        ctx = dict(
            devices=devices,
            event=event,
            # Make a bunch of timing counters available for the conditional to decide on
            # Each of these counts in seconds (float).
            since_last_event=None,      # when this event last occurred
            since_last_run=None,        # when this event last resulted in actions executed (no when: condition blocked)
            since_last_action_run=None  # same as above, but for each individual action.
            # If no valid value found, they are None. this means user must explicitly
            # handle None values if applicable, for example:
            # 'since_last_event|isnone(123) > 2' where isnone is a custom Jinja2 filter we have.
        )

        # Add any aliases with direct access. Aliases which are not valid names will just not be
        # reachable.
        for alias, dev_id in list(self.inventory.aliases.items()):
            ctx[alias] = devices[dev_id]

        if event_cfg['last_occurred'] is not None:
            ctx['since_last_event'] = event.timestamp - event_cfg['last_occurred']

        if event_cfg['last_ran'] is not None:
            ctx['since_last_run'] = time.time() - event_cfg['last_ran']

        event_cfg['last_occurred'] = event.timestamp

        # Evaluate shared conditional first
        if not conditional(ctx):
            self.log.debug("Not executing actions for %s ch %s '%s' event, conditional '%s' rejected", event.device_id.id, event.channel, event_type, event_cfg['when'])
            return

        event_cfg['last_ran'] = time.time()

        for action in actions:
            try:
                # Action-specific timer
                if action.last_ran is not None:
                    ctx['since_last_action_run'] = time.time() - action.last_ran
                elif 'since_last_action_run' in ctx:
                    ctx['since_last_action_run'] = None

                if action.conditional_expression(ctx):
                    action.handle_event(event)
                else:
                    self.log.debug("Not executing %s, conditional '%s' rejected", action, action.when)
            except:
                self.log.exception("Failed to execute action %s", action)


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
            action_target = list(action_config.keys())[0]
            single_value = list(action_config.values())[0]
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
        assert self.action_modules.get(name) is None, "Action %s already registered with %s" % (name, class_ref)
        self.action_modules[name] = class_ref


