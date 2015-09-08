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

from . import EventAction
from pyowmaster.exception import *
import pyowmaster.device.pio as pio

class SetPioAction(EventAction):
    """EventAction which tries to alter another PIO output port"""
    def __init__(self, inventory, dev, channel, event_type, method_name, action_config, single_value):
        super(SetPioAction, self).__init__(inventory, dev, channel, event_type, method_name, action_config, single_value)

        if single_value:
            # resolve single_value as <dev-id|alias>.<ch>
            (tgt_dev, tgt_ch_id) = self.parse_target(single_value)
            self.tgt_dev = tgt_dev
        else:
            tgt_dev_id = action_config.get('target', None)

            self.tgt_dev = self.inventory.find(tgt_dev_id)
            if not self.tgt_dev:
                raise ConfigurationError("Cannot find target device '%s'", tgt_dev_id)

            tgt_ch_id = action_config.get('target_channel', None)

        # Validate channel
        self.tgt_ch = None
        for ch in self.tgt_dev.channels:
            if ch.name == tgt_ch_id:
                if not ((ch.mode & pio.PIO_MODE_OUTPUT) == pio.PIO_MODE_OUTPUT):
                    raise ConfigurationError("Channel %s not configured as output" % ch.name)

                self.tgt_ch = ch
                break

        if not self.tgt_ch:
            raise ConfigurationError("Cannot find channel %s on device %s" % (tgt_ch_id, self.tgt_dev))

        # Normalise value Switch is True/False, where 'on' == True
        if method_name not in ('on', 'off'):
            raise ConfigurationError("Invalid setpio method '%s' on device %s ch %s" % (method_name, dev, channel))

        self.tgt_method = method_name

    def run(self, event):
        self.log.info("Setting value of %s ch %s to %s", self.tgt_dev, self.tgt_ch, self.tgt_method)
        try:
            value = {'on':True, 'off':False}[self.tgt_method]
            self.tgt_dev.set_output(self.tgt_ch, value)
        except OwnetError, e:
            self.log.error("Failed to execute SetPioValue action: %s", e)

    def __str__(self):
        return "SetPioAction[%s ch %s = %s]" % (self.tgt_dev.id, self.tgt_ch.name, self.tgt_method)

