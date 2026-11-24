"""Fixed receipt-bound engines for portable Material and Texture replay."""
from .write_binding import _component


PINS = {
    'material': ('dobe-material 0.4.1 (65f7bfd3e5f40d695d03162285879f0f8079ff6c)',
                 '2711c23762da15056049c11b0802e7cb751b47fca94f40d517ccb2848951be4b'),
    'texture': ('dobe-texture 0.6.1',
                '62a237a5c1af736450341623fa66c964baae72fcdaa96f765ef4c58a06f41fe3'),
}


def resolve(family):
    if type(family) is not str or family not in PINS:
        raise ValueError('a fixed Material or Texture replay engine is required')
    return _component(family, *PINS[family])
