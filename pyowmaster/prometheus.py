from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from pyowmaster.device import DS1820

class OwMasterPrometheusCollector:
    def __init__(self, owmaster, default_labels):
        self.owmaster = owmaster

        self.default_label_names = []
        self.default_label_values = []

        for k,v in default_labels.items():
            self.default_label_names.append(k)
            self.default_label_values.append(v)

    def collect(self):
        for k, v in self.owmaster.stats.values.items():
            k = k.replace('.', '_')
            metric_name = f'owmaster_{k}'

            type, value = v

            if type == 'gauge':
                m = GaugeMetricFamily(metric_name, '', labels=self.default_label_names)
            elif type == 'counter':
                m = CounterMetricFamily(metric_name, '', labels=self.default_label_names)
            else:
                raise Error(f'Invalid metric type in {k}: {type}')

            m.add_metric(self.default_label_values, value)
            yield m

        tries = GaugeMetricFamily('owfs_tries', 'owfs tries', labels=self.default_label_names + ['type'])
        for k, v in self.owmaster.owstats.tries.items():
            k = k.replace('.', '_')
            tries.add_metric(self.default_label_values + [k], v)
        yield tries

        errors = GaugeMetricFamily('owfs_errors', 'owfs error counters', labels=self.default_label_names + ['type'])
        for k, v in self.owmaster.owstats.errors.items():
            k = k.replace('.', '_')
            errors.add_metric(self.default_label_values + [k], v)
        yield errors

        temp_sensors = GaugeMetricFamily('ow_temperature_sensor', '1-Wire temperature sensors', labels=self.default_label_names + ['id', 'alias'])
        for dev in self.owmaster.inventory.list():
            if not dev.seen or dev.lost:
                continue

            if isinstance(dev, DS1820.DS1820):
                if dev.last is not None:
                    temp_sensors.add_metric(self.default_label_values + [dev.id, dev.alias or ''], dev.last)


        yield temp_sensors
