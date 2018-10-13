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
from pyowmaster.event.action import EventAction
import subprocess
import os


class ShellAction(EventAction):
    """EventAction which executes an arbitrary shell command"""
    def __init__(self, inventory, dev, channel, event_type, method, action_config, single_value):
        super(ShellAction, self).__init__(inventory, dev, channel, event_type, method, action_config, single_value)
        self.command = action_config.get('command', single_value)

    def run(self, event):
        # Blindly execute command
        # TODO: Parameter expansion?
        cmd = self.command

        self.log.info("Executing shell command %s", cmd)
        fnull = open(os.devnull, 'w')
        output = subprocess.check_output(cmd, stdin=fnull, stderr=subprocess.STDOUT, shell=True)
        fnull.close()
        self.log.debug("Command output: %s", output)

    def __str__(self):
        return "ShellAction[%s]" % self.command

