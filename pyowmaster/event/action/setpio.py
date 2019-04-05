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
from pyownet.protocol import OwnetError

from pyowmaster.event.action import EventAction
from pyowmaster.exception import *

class SetPioAction(EventAction):
    """EventAction which tries to alter another PIO output port"""
    def __init__(self, inventory, dev, channel, event_type, method, action_config, single_value):
        super(SetPioAction, self).__init__(inventory, dev, channel, event_type, method, action_config, single_value)

        if single_value:
            tgt = single_value
        else:
            tgt = action_config.get('target', None)

        if not tgt:
            raise ConfigurationError("No target configured for action")

        # resolve single_value as <dev-id|alias>.<ch>
        (tgt_dev, tgt_ch) = self.parse_target(tgt)

        # Validate channel
        if not tgt_ch:
            raise ConfigurationError("No valid channel found from %s" % tgt)

        if not tgt_ch.is_output:
            raise ConfigurationError("Device %s, channel %s not configured as output. Cannot use as setpio target" % (tgt_dev, tgt_ch))

        self.tgt_dev = tgt_dev
        self.tgt_ch = tgt_ch

        # Supported methods are on and off.
        if len(method) != 1:
            raise ConfigurationError("Invalid setpio method '%s' on device %s ch %s" % ('.'.join(method), dev, channel))

        method_name = method[0]
        if method_name not in ('on', 'off'):
            raise ConfigurationError("Invalid setpio method '%s' on device %s ch %s" % (method_name, dev, channel))

        self.tgt_method = method_name

    def run(self, event):
        try:
            value = {'on':True, 'off':False}[self.tgt_method]
            self.tgt_dev.set_output(self.tgt_ch, value)
        except OwnetError as e:
            self.log.error("Failed to execute SetPioValue action: %s", e)

    def __str__(self):
        return "SetPioAction[%s ch %s = %s]" % (self.tgt_dev.id, self.tgt_ch.name, self.tgt_method)
