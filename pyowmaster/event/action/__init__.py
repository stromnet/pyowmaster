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
import logging, re
from pyowmaster.exception import *

RE_DEV_CHANNEL = re.compile('([A-F0-9][A-F0-9]\.[A-F0-9]{12})\.([0-9AB])')
RE_ALIAS_CHANNEL = re.compile('([A-Za-z0-9\-\_]+)\.([0-9AB])')

class EventAction(object):
    """Base cloass to describe a parsed action which is to be executed when events on a specific device/channel/type occurs"""
    def __init__(self, inventory, dev, channel, event_type, method_name, action_config, single_value):
        """This signature represents how the ActionFactory tries to init each action"""
        self.inventory = inventory
        self.log = logging.getLogger(type(self).__name__)

    def parse_target(self, tgt):
        """Tries to parse a target string in the form <dev-id | alias>.<channel> into a valid
        device instance and string channel value (channel is not parsed nor verified)."""
        m = RE_DEV_CHANNEL.match(tgt)
        if m:
            dev_id = m.group(1)
            ch = m.group(2)

            target_dev = self.inventory.find(dev_id)
            if not target_dev:
                raise ConfigurationError("Cannot find device '%s'", dev_id)
        else:
            # Try alias
            m = RE_ALIAS_CHANNEL.match(tgt)
            if not m:
                raise ConfigurationError("Cannot resolve device target '%s'", tgt)

            alias = m.group(1)
            ch = m.group(2)

            target_dev = self.inventory.find_alias(alias)
            if not target_dev:
                raise ConfigurationError("Cannot find device '%s'", alias)

        return (target_dev, ch)


