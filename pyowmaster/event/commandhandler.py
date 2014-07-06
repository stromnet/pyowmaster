# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
from handler import ThreadedOwEventHandler
from events import *
import subprocess, re

def create(config_get, inventory):
    return CommandEventHandler(config_get, inventory)

RE_DEV_CMD = re.compile('([A-F0-9][A-F0-9]\.[A-F0-9]{12})\.([0-9AB])=(on|off)')
class CommandEventHandler(ThreadedOwEventHandler):
    """A EventHandler which reacts to OwSwitchEvents and executes commands based on these"""
    def __init__(self, config_get, inventory, max_queue_size=0):
      super(CommandEventHandler, self).__init__(max_queue_size)
      self.config_get = config_get
      self.inventory = inventory
      self.start()

    def handle_event_blocking(self, event):
        if not isinstance(event, OwSwitchEvent):
            return

        if event.value == OwSwitchEvent.ON:
            cmd_key = 'command.ch.%s.on' % event.channel
        elif event.value == OwSwitchEvent.OFF:
            cmd_key = 'command.ch.%s.off' % event.channel
        elif event.value == OwSwitchEvent.TRIGGED:
            cmd_key = 'command.ch.%s.trigged' % event.channel

        self.log.debug("Looking for command for %s", cmd_key)
        cmd = self.config_get(event.deviceId.id, cmd_key, None)
        if not cmd:
            return

        # Try to resolve command
        # Valid forms:
        # <nn.nnnnnnnnnnn>.<ch>=1/0
        # shell:<cmd>
        # Multiple commands can be sent by , separating them
        for cmd in cmd.split(","):
            if cmd.find("shell:") == 0:
                # Blindly execute command
                cmd = cmd[6:]
                self.log.info("Executing command %s", cmd)
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
                self.log.debug("Command output: %s", output)
            else:
                m = RE_DEV_CMD.match(cmd)
                if not m:
                    raise Exception("Illegal command %s" % cmd)
        
                self.log.info("Executing command %s", cmd)
                # Find device
                devId = m.group(1)
                ch = m.group(2)
                value = m.group(3)

                dev = self.inventory.find(devId)
                if not dev:
                    raise Exception("Cannot find device %s referenced in command %s" % (devId, cmd_key))
                
                dev.set_output(ch, True if value == "on" else False)



