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
import collections
import queue
import time
import threading
from six import binary_type, text_type, integer_types, PY2

import requests, requests.exceptions

from pyowmaster.event.handler import OwEventHandler
from pyowmaster.event.events import *


def create(inventory):
    tsdb = InfluxDBEventHandler()
    return tsdb


# Escape functions borrowed from official influxdb line_protocol.py
def _escape_tag(tag):
    tag = _get_unicode(tag, force=True)
    return tag.replace(
        "\\", "\\\\"
    ).replace(
        " ", "\\ "
    ).replace(
        ",", "\\,"
    ).replace(
        "=", "\\="
    )


def _escape_value(value):
    value = _get_unicode(value)
    if isinstance(value, text_type) and value != '':
        return "\"{0}\"".format(
            value.replace(
                "\"", "\\\""
            ).replace(
                "\n", "\\n"
            )
        )
    elif isinstance(value, integer_types) and not isinstance(value, bool):
        return str(value) + 'i'
    else:
        return str(value)


def _get_unicode(data, force=False):
    """
    Try to return a text aka unicode object from the given data.
    """
    if isinstance(data, binary_type):
        return data.decode('utf-8')
    elif data is None:
        return ''
    elif force:
        if PY2:
            return unicode(data)
        else:
            return str(data)
    else:
        return data


class InfluxDBEventHandler(OwEventHandler):
    """A EventHandler which sends all numeric events into InfluxDb

    Basic flow is:
    1. Events arrive in handle_event, and are translated into "lines" (or dropped).
    2. Each line is put on a FIFO queue.
       If the queue is full, the oldest item is dropped.
       THe max size is controlled by max_queue_size.
    
    The actual sending is done in a separate thread:

    3. Drain lines (events) from queue (which is feed from main thread as described above)
       If there are no events pending, we block until there are.
       If there are events pending in the current batch, and that is the only batch, we wait up
       to max_linger seconds before we stop the waiting.
       An exception is if we have multiple pending batches, in which case we don't block at all.

    4. Put any new lines into batch
       If batch size exceeds max_batch_size, create a new batch.
       If number of batches exceeds max_batches, drop the oldest batch.

    5. Try to send all batches
       If send fails, it will behave as described above. Normally this means we
       block for max_linger seconds, waiting for new events, and then try to re-send.

    6. Repeat from 3.

    The modules configuration options are as follows:

        - server            The server to send messages to, default 'http://localhost:8086'
        - database          Name of the influxdb database to send to. Default 'owfs'
        - retention_policy  Name of the retention policy to apply, if any. Default None
        - max_queue_size    Max queue size between main and send thread.
                            If overflowed, events are dropped. Default 5000
        - max_batches       Maximum number of batches to allow in memory.
                            If overflowed, batches of events are dropped. Default 10
        - max_batch_size    Maximum lenght of single batch. Default 500.
        - max_linger        How many seconds to wait for new events before sending batch.
                            Default: 3.0
        - extra_tags        A dict of string->string with extra tags to send for each metric.

    With the default settings, we hold max 10*500 = 50000 lines in memory if InfluxDB is down.
    If an average line is 80b, we use 4MB. The primary queue should ideally never be full.
    """
    def __init__(self):
        super(InfluxDBEventHandler, self).__init__()
        self.queue = None
        self.thread = threading.Thread(target=self._run)
        self.session = requests.Session()

    def config(self, module_config, root_config):
        self.max_queue_size = module_config.get('max_queue_size', 5000)
        self.max_batches = module_config.get('max_batches', 100)
        self.max_batch_size = module_config.get('max_batch_size', 500)
        self.max_linger = module_config.get('max_linger', 3.0)

        self.server = module_config.get('server', 'http://localhost:8086')
        while self.server.endswith('/'):
            self.server = self.server[0:-1]

        username = module_config.get('username', None)
        password = module_config.get('password', None)
        if username is not None and password is not None:
            self.session.auth = (username, password)
        else:
            self.session.auth = None

        self.database = module_config.get('database', 'owfs')
        self.retention_policy = module_config.get('retention_policy', None)

        # These can be overriden
        self.measurement_name = {
            'reading':'owfs_reading',
            'stats':'owfs_stats'
        }

        self.sensor_key = 'sensor'
        self.alias_key = 'alias'
        self.type_key = 'type'
        self.channel_key = 'ch'

        # String with key=word pairs, comma-separated as in line protocol
        extra_tags = module_config.get('extra_tags', None)
        self.extra_tags = {}
        if extra_tags:
            if isinstance(extra_tags, collections.abc.Mapping):
                self.extra_tags.update(extra_tags)

        self.start()

    def start(self):
        if not self.thread.isAlive():
            self.log.debug("InfluxDB handler configured for %s, database %s",
                           self.server, self.database)

            self.queue = queue.Queue(self.max_queue_size)
            self.thread.start()

    def handle_event(self, event):
        """Handle, format and enqueue the event"""
        measurement_type = 'reading'
        field_name = "value"
        if isinstance(event, OwTemperatureEvent):
            type_value = "temperature"
        elif isinstance(event, OwCounterEvent):
            type_value = "counter"
        elif isinstance(event, OwAdcEvent):
            type_value = "gauge"
        elif isinstance(event, OwStatisticsEvent):
            measurement_type = 'stats'
            type_value = "%s" % event.category
        else:
            return

        tags = {
                'type': type_value
            }

        if event.device_id and event.device_id.id:
            tags[self.sensor_key] = event.device_id.id

        if self.alias_key:
            if isinstance(event, OwStatisticsEvent):
                tags[self.alias_key] = event.name
            elif event.device_id.alias:
                tags[self.alias_key] = event.device_id.alias

        if hasattr(event, 'channel') and event.channel is not None:
            tags[self.channel_key] = event.channel

        if self.extra_tags:
            tags.update(self.extra_tags)

        tags_str = ''
        for k in sorted(tags.keys()):
            tags_str += ',%s=%s' % (_escape_tag(k), _escape_tag(tags[k]))

        # InfluxDB only allows one type of data for a specific field
        # As we use 'value' for all, we must use float.
        value = float(event.value)

        # Line protocol is measurement,<tags> <values> <timestamp>
        line = '%s%s %s=%s %d' % (
            self.measurement_name[measurement_type],
            tags_str,
            field_name,
            _escape_value(value),
            event.timestamp)

        # Put onto queue. If full, drop oldest item
        while True:
            try:
                self.queue.put(line, False)
                return
            except queue.Full:
                try:
                    self.queue.get(False)
                except queue.Empty:
                    # Could have been drained by other end
                    pass

    def _run(self):
        """Main loop of the thread. Drains the incoming queue of lines, batches them and then
        sends them.
        """
        self.log.debug("Main loop entered")

        batches = LineBatches(self.log, self.max_batches, self.max_batch_size)

        exit_requested = 0
        last_send_ok = True
        while True:
            try:
                # First drain queue of items into local batch
                # Under normal operations, we drain the items in the queue,
                # put them in one or more batches (controlled by max_batch_size,
                # and then send all batches.
                # In case of send issues, more batches may be backed up.
                timeout_at = time.time() + self.max_linger
                # If exit has been signaled, there won't be any more to drain.
                while not exit_requested:
                    block = True
                    if batches.empty():
                        # If there are non pending, and no new, it will block.
                        timeout = None
                    elif batches.backlogged() and last_send_ok:
                        # If our batch sending has failed earlier (and is backlogged), do not wait
                        # at all, just try to drain the old batches first.
                        # Normally in failures, last_send_ok will be False, and we will
                        # block anyway (backing of the server a bit).
                        # Once a backlogged batch has been sent though, keep fireing them away
                        # until not backlogged anymore.
                        block = False
                        timeout = 0
                    else:
                        # There are pending in current batch, block for up to max_linger seconds
                        # to allow more items to arrive into same batch.
                        timeout = timeout_at - time.time()
                        if timeout < 0:
                            # We've waited enough already. Don't wait anymore.
                            break

                    #self.log.debug("Polling jobs (timeout=%s)", timeout)
                    try:
                        line = self.queue.get(block, timeout)
                        self.queue.task_done()
                    except queue.Empty:
                        # End batch-fill loop
                        break

                    if line:
                        batches.add(line)
                    else:
                        exit_requested = 1

                # Draining of queue done. Let's send them.
                if not batches.empty():
                    batch = batches.peek()
                    self.log.debug("Send batch with %d metrics (%d batches pending)",
                                   len(batch), len(batches) - 1)

                    last_send_ok = False
                    if self.send(batch):
                        # Sucessfully sent, remove the batch
                        batches.sent()
                        last_send_ok = True
                    elif exit_requested > 0:
                        # We've failed to send, and we're trying to exit..
                        # Retry up to 3 times, with the linger-timeout as backoff delay
                        exit_requested = exit_requested + 1
                        if exit_requested > 3:
                            self.log.warning("Gave up on sending metrics during shutdown. Discarding")
                            break
                        else:
                            self.log.warning("Failed to send metrics during shutdown, retrying")
                            time.sleep(self.max_linger)

                elif exit_requested:
                    self.log.debug("All batches sent, exit signaled. Returning")
                    break

            except:
                self.log.error("Unhandled exception in InfluxDB send thread", exc_info=True)
                if exit_requested:
                    break

        self.log.debug("Main loop exited")

    def shutdown(self):
        if self.queue:
            # Wait for queue to empty on regular events
            self.queue.join()
            # Then ask backend to exit
            self.log.debug("Sending Shutdown to thread")
            self.queue.put(None)

        if self.thread.isAlive():
            self.thread.join()

        self.session.close()

    def send(self, lines):
        """Send a batch of lines using the HTTP Line protocol

        Returns True if succssfull, False otherwise."""
        try:
            params = {'precision': 's', 'db': self.database}
            if self.retention_policy:
                params['rp'] = self.retention_policy

            self.log.debug("Sending %d lines to InfluxDB at %s", len(lines), self.server)
            #self.log.debug("Data: %s", lines)

            data = "\n".join(lines)
            r = self.session.request(
                    url=(self.server + '/write'),
                    method='POST',
                    params=params,
                    headers={'Content-type': 'application/octet-stream'},
                    data=data)

            if r.status_code == 204:
                self.log.debug("InfluxDB accepted our data")
                return True
            elif 500 <= r.status_code < 600:
                self.log.warning("InfluxDB server error (%d): %s", r.status_code, r.text)
                return False
            else:
                if r.status_code == 400:
                    # Bad request / input data
                    faulty = len(lines)
                    if faulty > 1:
                        # Send each line by itself, possibly allows us to identify which
                        # line is faulty (and at least send the valid ones)
                        self.log.info("InfluxDB client error (%d: %s). Sending line by line", r.status_code, r.text)
                        for line in lines:
                            if self.send([line]):
                                # One less which failed..
                                faulty -= 1

                        if faulty > 0:
                            self.log.warning("Discarding %d lines of faulty data", faulty)

                        return True
                    else:
                        # Single line which we can report as invalid
                        self.log.error("InfluxDB client error (%d) for line '%s': %s",
                                       r.status_code, lines[0], r.text)
                        return False

                # Something else
                return False

        except requests.exceptions.RequestException as e:
            self.log.warning("Failed to talk to InfluxDB: %s", e)
            return False


class LineBatches(object):
    def __init__(self, log, max_batches, max_batch_size):
        self.log = log
        self.max_batches = max_batches
        self.max_batch_size = max_batch_size
        self.batches = []
        self._add_batch()

    def __len__(self):
        return len(self.batches)

    def add(self, item):
        self.w_batch.append(item)
        if len(self.w_batch) >= self.max_batch_size:
            self._add_batch()

    def _add_batch(self):
        while len(self.batches) >= self.max_batches:
            # Remove oldest
            self.log.warning("Dropping a batch with %d metrics", len(self.batches[0]))
            self.batches.pop(0)

        self.batches.append([])
        self.w_batch = self.batches[-1]

    def empty(self):
        return len(self.batches) == 1 and len(self.w_batch) == 0

    def backlogged(self):
        return len(self.batches) > 1

    def peek(self):
        return self.batches[0]

    def sent(self):
        if len(self.batches) == 1:
            # Single batch, just clear it and re-use it
            del self.batches[0][:]
        else:
            self.batches.pop(0)
