import jinja2


def parse_conditional(when, jinja_env):
    if when is not None:
        if isinstance(when, bool):
            return lambda _: when
        else:
            return jinja_env.compile_expression(when)
    else:
        return lambda _: True


def ifnone_filter(value, alternative_value):
    if value is None:
        return alternative_value
    return value


def init_jinja2():
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters['ifnone'] = ifnone_filter
    return env
