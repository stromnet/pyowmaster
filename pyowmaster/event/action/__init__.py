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
import logging
import time

from pyowmaster.event.action.conditionals import parse_conditional
from pyowmaster.exception import *


class EventAction(object):
    """Base class to describe a parsed action which is to be executed when events on a specific device/channel/type occurs"""
    def __init__(self, inventory, dev, channel, event_type, method, action_config, single_value):
        """This signature represents how the ActionFactory tries to init each action"""
        self.inventory = inventory
        self.log = logging.getLogger(type(self).__name__)
        self.last_ran = None

        # Check if we should react to is_reset values (default true)
        self.include_reset_events = action_config.get('include_reset', False)

        # It's also possible to add '.include_reset' suffix to the method name
        if "include_reset" in method:
            self.include_reset_events = True
            del method[method.index('include_reset')]

    def init_conditional(self, action_config, jinja_env):
        # Conditional execution
        self.when = action_config.get('when', None)
        self.conditional_expression = parse_conditional(self.when, jinja_env)

    def parse_target(self, tgt):
        """Tries to parse a target string in the form <dev-id | alias>.<channel> into a valid
        device instance and string channel value (channel is not parsed nor verified)."""
        (target_dev, ch) = self.inventory.resolve_target(tgt)

        if not target_dev:
            raise ConfigurationError("Cannot find device '%s'", tgt)

        if ch == False:
            raise ConfigurationError("Device has no channel as indicated in target '%s'", tgt)

        return (target_dev, ch)

    def handle_event(self, event):
        if not self.include_reset_events and event.is_reset:
            self.log.debug("%s: Ignoring event, marked as reset-value", self)
            return

        self.log.debug("%s: Executing action", self)
        self.last_ran = time.time()
        self.run(event)

