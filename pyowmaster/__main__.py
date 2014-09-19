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
import logging
import ConfigParser, sys
import time

from pyownet.protocol import *
from . import OwMaster


def setup_logging(logfile):
    """Setup basic logging to console + a logfile"""
    fmt="%(asctime)-15s %(thread)d %(levelname)-5s %(name)-10s %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=fmt)

    fh = logging.FileHandler(logfile, 'a')
    fh.setFormatter(logging.Formatter(fmt, None))
    fh.setLevel(logging.INFO)
    logging.Logger.root.addHandler(fh)


def read_config(cfgfile):
    """Read config from file using ConfigParser"""
    cfg.read(cfgfile)
    set_config(cfg)


# Default, empty config
cfg = ConfigParser.ConfigParser()
def set_config(cfgparser):
    """Allow setting of global ConfigParser object"""
    cfg = cfgparser

def config_get(sections, option, default=None):
    """Helper function to fetch data from global ConfigParser object,
    with support for default and multiple (fallback) sections"""

    if type(sections) != tuple:
        sections = (sections,)

    for section in sections:
        if not cfg.has_option(section, option):
            continue

        data = cfg.get(section, option)
        if default != None:
            if isinstance(default, long):
                return long(data)
            if isinstance(default, int):
                return int(data)
            if isinstance(default, float):
                return float(data)
        return data

    return default

def main(cfgfile=None, config_get_fn=None, configure_logging=True):
    if cfgfile:
        read_config(cfgfile)

    if not config_get_fn:
        config_get_fn = config_get


    if configure_logging:
        setup_logging(config_get('owmaster', 'logfile', 'owmaster.log'))

    log = logging.getLogger(__name__)

    try:
        owm = None
        flags = 0
        temp_unit = config_get('owmaster', 'temperature_unit', 'C').upper()
        if temp_unit == 'C': flags |= FLG_TEMP_C
        elif temp_unit == 'F': flags |= FLG_TEMP_F
        elif temp_unit == 'K': flags |= FLG_TEMP_K
        elif temp_unit == 'R': flags |= FLG_TEMP_R
        else: raise Exception("Invalid temperature_unit")
        #flags| = FLG_PERSISTENCE

        ow_port = config_get('owmaster', 'owserver_port', 4304)
        tries = 0
        while True:
            try:
                owm = OwMaster(OwnetProxy(port=ow_port,verbose=False, flags=flags), config_get_fn)
                break
            except ConnError, e:
                tries+=1
                backoff = min((tries * 2) + 1, 60)
                log.warn("Failed initial connect to owserver on port %d, retrying in %ds: %s", ow_port, backoff, e)
                time.sleep(backoff)

        owm.main()
    finally:
        if owm:
            owm.shutdown()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "owmaster.cfg")

