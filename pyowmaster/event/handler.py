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
import threading,Queue

class OwEventHandler(object):
    """Abstract basic event handler interface"""
    def __init__(self):
        self.log = logging.getLogger(type(self).__name__)
        pass

    def _init_config(self, root_config, cfg_module_name):
        self.cfg_module_name = cfg_module_name
        self._update_config(root_config)

    def _update_config(self, root_config):
        module_config = root_config.get(('modules', self.cfg_module_name), {})
        self.config(module_config, root_config)

    def config(self, module_config, root_config):
        """This should be implement if reading from config is required"""
        pass

    def handle_event(self, event):
        """Handle the event in some way. Should not raise exceptions, and it may not perform
        any blocking operations."""
        pass

    def shutdown(self):
       """Signals the handler to shut down"""
       pass


class OwEventDispatcher(OwEventHandler):
    """Dispatcher which forwards events on a set of event handlers"""
    def __init__(self):
        self.log = logging.getLogger(type(self).__name__)
        self.handlers = []

        self.paused = False
        self.pause_queue = []

    def add_handler(self, handler):
        """Add a handler to be executed"""
        self.handlers.append(handler)

    def refresh_config(self, root_config):
        """Refresh config for all handlers"""
        for h in self.handlers:
            try:
                h._update_config(root_config)
            except:
                self.log.error("Unhandled exception configuring event handler %s", h, exc_info=True)

    def pause(self):
        """Pause the dispatching of any events, and let the be queued up instead"""
        self.paused = True

    def resume(self):
        """Resume event dispatching, immediately dispatch any queued up events"""
        self.paused = False
        for event in self.pause_queue:
            self._emit_event(event)

        self.pause_queue = []

    def handle_event(self, event):
        """Take the event, and let each registered handler deal with it.
        If an exception is thrown, we log the exception but do not let it take us down.
        If the dispatcher is paused, we queue the event"""

        if self.paused:
            if len(self.pause_queue) >= 100:
                self.log.warn("Pause queue is %d entries long, dropping oldest", len(self.pause_queue))
                self.pause_queue.pop(0)

            self.pause_queue.append(event)
        else:
            self._emit_event(event)

    def _emit_event(self, event):
        self.log.debug("Handling %s", event)
        for h in self.handlers:
            try:
                h.handle_event(event)
            except:
                self.log.error("Unhandled exception in event handler %s", h, exc_info=True)

    def shutdown(self):
        """Signals all registered handlers to shut down"""
        for h in self.handlers:
            h.shutdown()
      

class ThreadedOwEventHandler(OwEventHandler):
    def __init__(self, max_queue_size=0):
        super(ThreadedOwEventHandler, self).__init__()
        self.thread = threading.Thread(target=self._run)
        self.queue = Queue.Queue(maxsize=max_queue_size)

    def start(self):
        if not self.thread.isAlive():
            self.thread.start()

    def handle_event_blocking(self, event):
        """Allow the subclass to handle the event, blocking allowed here"""
        raise Exception("handle_event_blocking must be implemented")

    def handle_event(self, event):
        """Puts the event onto the thread queue"""
        self.queue.put(event)

    def _run(self):
        """Main loop of the thread"""
        self.log.debug("Main loop entered")
        while True:
            event = self.queue.get(True)
            try:
                if event:
                    self.handle_event_blocking(event)
            except:
                self.log.error("Unhandled exception handling event %s", event, exc_info=True)
            finally:
                self.queue.task_done()

            if not event:
                break

        self.log.debug("Main loop exited")
            
    def cleanup(self):
        """Empty method executed after shutdown has returned and all queued events have been processed"""
        pass

    def shutdown(self):
        # Wait for queue to empty
        self.queue.join()
        self.queue.put(None)
        self.thread.join()

        self.cleanup()

