# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :
"""A version of the stock sched module with support for multiple queues with
different priorities.
The difference compared to the sched priority support is that we submit jobs to
different queues, not the same queue with different per-event priorities.

This solves the problem when multiple events are submitted, having an earlier time
than a prioritized one, but taking so long that the more prioritized event is delayed
long after we want to execute it.

To use, create one scheduler instance, and then create one or more queues.
The queues are prioritzed in the order they are created, first has highest priority.

Lots of code copied from base sched implementation. The main usage differences are:
- time and delay are functions which can be overriden by subclassing
- multiple queues are created manually
- events are submitted to individual queues rather than scheduler

"""
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
import heapq
import time
from collections import namedtuple
Event = namedtuple('Event', 'time, action, argument')

class scheduler(object):
    def __init__(self):
        self._queues = []

    def time(self):
        """Return the current time; in this implementation this returns seconds
        as returned from time.time()
        """
        return time.time()

    def delay(self, duration):
        """Delays for the specified duration, where duration should be the same unit as
        the time method uses. In this implementation we use time.sleep
        """
        return time.sleep(duration)

    def create_queue(self, min_dispatch=1, max_dispatch=10000):
        """Create a new queue, with lower priority than the preivously created queue

        The min_dispatch parameter tells how many events we should try to execute, before
        allowing a higher priority queue to execute again.
        A higher min_dispatch value ensures this queue is not starved due to too many
        jobs on the higher priority queues.

        The max_dispatch parameter tells how many events we are allowed to execute in one
        go, before checking back on the main queues.
        This is usefull if we have lots of lower-prio events, and we want them to be able
        to add events to a higher-prio queue and have them executed.
        Another scenario when this is useful if we have a lots of events in a queue, and want
        to pop back to the scheduler run() method to check if we are shutting down.

        """
        queue = Queue(self.time, min_dispatch, max_dispatch)
        self._queues.append(queue)
        return queue

    def run(self):
        """Execute events until all the queues are empty.

        For each created queue, we will check if any events are queued and if they
        are ready to execute. If ready to execute, we will remove the item from the
        queue and execute it. This will block until the event action returns.

        The first queue, the one with highest prio, will always execute
        any number of items, but at most max_dispatch as configured.
        Any subsequent queues will also be limited to execute no longer
        than the previous queues "next" limit is hit. However, at least
        min_dispatch events will be executed on all queues.

        If no queues have any event immediately ready for execution,
        the delay function is called. If the delay function returns prematurely,
        it is simply restarted.

        It is legal for both the delay function and the action
        function to modify the queue or to raise an exception;
        exceptions are not caught but the scheduler's state remains
        well-defined so run() may be called again.
        """
        # localize variable access to minimize overhead
        # and to improve thread safety
        q = self._queues
        self.do_run = True
        num_queues = len(q)
        while self.do_run:
            next_at = 0
            now = self.time()
            for i in range(num_queues):
                # Dispatching with next_at restricts the queue from dispatching actions
                # when the higher prioritized queues are ready to go
                qAt = q[i].dispatch(now, next_at)
                if qAt != 0 and (next_at == 0 or qAt < next_at):
                    next_at = qAt

            # If no queues have any events at all, we are done.
            if next_at == 0:
                return

            # Delay until next event, if necessary
            now = self.time()
            if next_at > now:
                self.delay(next_at - now)


class Queue(object):
    def __init__(self, timefunc, min_dispatch, max_dispatch):
        self._queue = []
        self.timefunc = timefunc
        self.min_dispatch = min_dispatch
        self.max_dispatch = max_dispatch

    def enterabs(self, at_time, action, argument):
        """Enter a new event in the queue at an absolute time.

        Returns an ID for the event which can be used to remove it,
        if necessary.

        """
        if not argument:
            argument = []
        event = Event(at_time, action, argument)
        heapq.heappush(self._queue, event)
        return event # The ID

    def enter(self, delay, action, argument=None):
        """A variant that specifies the time as a relative time.

        This is actually the more commonly used interface.
        """
        at_time = self.timefunc() + delay
        return self.enterabs(at_time, action, argument)

    def cancel(self, event):
        """Remove an event from the queue.

        This must be presented the ID as returned by enter().
        If the event is not in the queue, this raises ValueError.

        """
        self._queue.remove(event)
        heapq.heapify(self._queue)

    def dispatch(self, now, not_later_than):
        """Internal dispatch function, to be called from the scheduler only.

        Will dispatch events which are scheduled to execute on or after 'now'.
        The timestamp is passed as parameter to let all queues execute using the same
        relative time, to avoid one queue with long-running events to steal all time.

        If not_later_than is non-0, we will stop executing of events when the timefunc
        returns greater than or equal value than not_later_than. Note that this uses the
        real time, not the static 'now' passed as parameter.
        If a higher-priority queue has pending events, this will ensure that those events
        are executed even if this lower-priority queue has jobs ready for execution.
        We will however always dispatch at least min_dispatch events, if available. This avoids
        queue starvation if higher prioritized queues have lots of/frequent events.
        """
        pop = heapq.heappop
        q = self._queue

        dispatched = 0
        while q:
            time, action, argument = checked_event = q[0]
            if now < time:
                # Not ready for dispatch yet, tell scheduler when the next event is ready to go
                return time

            if dispatched >= self.min_dispatch and \
                (dispatched < self.max_dispatch or \
                 (not_later_than > 0 and self.timefunc() >= not_later_than)):
                # We've executed our minimum amount of events,
                # but are now not allowed to execute any more.
                return time

            event = pop(q)
            # Verify that the event was not removed or altered
            # by another thread after we last looked at q[0].
            if event is checked_event:
                action(*argument)
                dispatched += 1
            else:
                heapq.heappush(q, event)

        # Queue empty
        return 0

    @property
    def queue(self):
        """An ordered list of upcoming events.

        Events are named tuples with fields for:
            time, priority, action, arguments

        """
        # Use heapq to sort the queue rather than using 'sorted(self._queue)'.
        # With heapq, two events scheduled at the same time will show in
        # the actual order they would be retrieved.
        events = self._queue[:]
        return map(heapq.heappop, [events]*len(events))

