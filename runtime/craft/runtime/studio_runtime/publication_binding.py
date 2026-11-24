"""Fixed receipt-bound engines for publication and animation replay."""
from .write_binding import _component


PINS = {
    'layout': ('dobe-layout 0.20.1',
               'fd76bca333a61e886b6a6394dfcbba99bfb9650a1b6b4f5393f7d210dba8001d'),
    'interface': ('dobe-interface 0.18.1',
                  '214076a2a842b48864a840f85943bf7202987334e03ed472ef7f4ef6ef5ca8ad'),
    'animate': ('dobe-animate 0.2.1',
                '16ae0ce95db0064b435ca34cb6d20d031e84d641f5be9559424cf3cc35a46790'),
}


def resolve(family):
    if type(family) is not str or family not in PINS:
        raise ValueError('a fixed Layout, Interface or Animate replay engine is required')
    return _component(family, *PINS[family])
