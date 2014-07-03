from pyownet.protocol import OwnetProxy,FLG_PERSISTENCE
from pyowmaster import OwMaster

import logging

fmt="%(asctime)-15s %(levelname)-5s %(name)-10s %(message)s"
logging.basicConfig(level=logging.DEBUG, format=fmt)
fh = logging.FileHandler('owmaster.log', 'a')
fh.setFormatter(logging.Formatter(fmt, None))
fh.setLevel(logging.INFO)
logging.Logger.root.addHandler(fh)

import ConfigParser, sys
cfg = ConfigParser.ConfigParser()
cfg.read(sys.argv[1] if len(sys.argv) > 1 else "owmaster.cfg")

def config_get(section, option, default=None):
	if not cfg.has_option(section, option):
		return default

	data = cfg.get(section, option)
	if default != None:
		if isinstance(default, long):
			return long(data)
		if isinstance(default, int):
			return int(data)
	return data

ow_port = config_get('owserver', 'port', 4304)

owm = OwMaster(OwnetProxy(port=ow_port,verbose=False), config_get)#,flags=FLG_PERSISTENCE))
owm.main()
