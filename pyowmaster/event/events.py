# vim: set expandtab sw=4 softtabstop=4 fileencoding=utf8 :

class OwEventBase(object):
    """Base object for any events sent emitted from
    1-Wire devices as result of alarms or regular polling"""
    def __init__(self, timestamp):
        self.timestamp = timestamp
        self.deviceId = None

    def __str__(self):
        return "OwEvent[%s, unknown]" % (self.deviceId)

class OwCounterEvent(OwEventBase):
    """Describes an counter reading"""
    def __init__(self, timestamp, channel, value):
        super(OwCounterEvent, self).__init__(timestamp)
        self.channel = channel
        self.value = value

    def __str__(self):
        return "OwCounterEvent[%s, ch %s, %d]" % (self.deviceId, self.channel, self.value)

class OwTemperatureEvent(OwEventBase):
    """Describes an temperature reading"""
    def __init__(self, timestamp, value, unit):
        super(OwTemperatureEvent, self).__init__(timestamp)
        self.value = value
        self.unit = unit

    def __str__(self):
        return "OwTemperatureEvent[%s, %.2f %s]" % (self.deviceId, self.value, self.unit)

class OwSwitchEvent(OwEventBase):
    """Describes an event which has occured on the specified OwDevice ID/channel.

    For momentary inputs, the value is always TRIGGED
    For toggle inputs, and outputs, the value is either ON or OFF.

    The channel identifier is device specific, but is generally 'A' or 'B', or a numeric.
    """
    OFF = "OFF"
    ON = "ON"
    TRIGGED = "TRIGGED"

    def __init__(self, timestamp, channel, value):
        super(OwSwitchEvent, self).__init__(timestamp)
        self.channel = channel
        self.value = value

    def __str__(self):
        return "OwSwitchEvent[%s, ch %s, %s]" % (self.deviceId, self.channel, self.value)



