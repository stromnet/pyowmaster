# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
import logging
import threading,Queue

class OwEventHandler(object):
    """Abstract basic event handler interface"""
    def __init__(self):
        self.log = logging.getLogger(type(self).__name__)
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

    def add_handler(self, handler):
        """Add a handler to be executed"""
        self.handlers.append(handler)

    def handle_event(self, event):
        """Take the event, and let each registered handler deal with it.
        If an exception is thrown, we log the exception but do not let it take us down"""

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
        self.thread.start()

    def handle_event_blocking(self, event):
        """Allow the subclass to handle the event, blocking allowed here"""
        raise Error("handle_event_blocking must be implemented")

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
            

    def shutdown(self):
        # Wait for queue to empty
        self.log.debug("Shutting down")
        self.queue.join()
        self.log.debug("Killing worker..")
        self.queue.put(None)
        self.log.debug("Awating threa dterminat")
        self.thread.join()

