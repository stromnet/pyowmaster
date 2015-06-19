# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :

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
import logging, logging.config
import ConfigParser, sys, yaml
import time

from pyownet.protocol import *
from . import OwMaster
from ecollections import EnhancedMapping

class Main:
    def __init__(self):
        self.owm = None
        self.cfgfile = None

    def run(self, cfgfile=None, configure_logging=True):
        self.cfgfile = cfgfile
        self.reload_config()

        if configure_logging:
            self.setup_logging()

        log = self.log = logging.getLogger(__name__)

        try:
            flags = 0
            temp_unit = self.cfg.get('owmaster:temperature_unit', 'C').upper()
            if temp_unit == 'C': flags |= FLG_TEMP_C
            elif temp_unit == 'F': flags |= FLG_TEMP_F
            elif temp_unit == 'K': flags |= FLG_TEMP_K
            elif temp_unit == 'R': flags |= FLG_TEMP_R
            else: raise Exception("Invalid temperature_unit")
            #flags| = FLG_PERSISTENCE

            ow_port = self.cfg.get('owmaster:owserver_port', 4304)
            tries = 0
            while True:
                try:
                    self.owm = OwMaster(OwnetProxy(port=ow_port,verbose=False, flags=flags), self.cfg)
                    break
                except ConnError, e:
                    tries+=1
                    backoff = min((tries * 2) + 1, 60)
                    log.warn("Failed initial connect to owserver on port %d, retrying in %ds: %s", ow_port, backoff, e)
                    time.sleep(backoff)

            self.owm.main()
        finally:
            if self.owm:
                self.owm.shutdown()

    def setup_logging(self, is_reload=False):
        """Setup logging based on the logconfig specified"""
        logcfg = self.cfg.get('logging', {'version': 1})

        if is_reload:
            logcfg['incremental'] = True

        logging.config.dictConfig(logcfg)

    def reload_config(self):
        if not self.cfgfile:
            return

        # Reset config and re-read from cfgfile
        if hasattr(self, 'log'):
            self.log.debug("Reloading %s", self.cfgfile)

        with open(self.cfgfile) as f:
            cfg = yaml.load(f)
            if not cfg:
                cfg = {}

            self.cfg = EnhancedMapping(cfg)

        import pprint
        pprint.pprint(self.cfg)

        if self.owm:
            self.owm.refresh_config(self.cfg)
            self.setup_logging(True)


import code, traceback, signal

def debug(sig, frame):
    """Interrupt running process, and provide a python prompt for
    interactive debugging."""
    d={'_frame':frame}         # Allow access to frame object.
    d.update(frame.f_globals)  # Unless shadowed by global
    d.update(frame.f_locals)

    i = code.InteractiveConsole(d)
    message  = "Signal received : entering python shell.\nTraceback:\n"
    message += ''.join(traceback.format_stack(frame))
    i.interact(message)

def sighup(sig, frame):
    main.reload_config()

def sig_listen():
    signal.signal(signal.SIGUSR1, debug)
    signal.signal(signal.SIGHUP, sighup)

if __name__ == "__main__":
    sig_listen()
    main = Main()
    main.run(sys.argv[1] if len(sys.argv) > 1 else "owmaster.yaml")

