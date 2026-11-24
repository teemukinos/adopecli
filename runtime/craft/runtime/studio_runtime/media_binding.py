"""Fixed receipt-bound engines for native media replay."""
import platform

from .write_binding import _component


AUDIO_LOCK = '182c397dde73bc5bff2b10968da6b7659b4a1c0dd20ae8a8ee942a41656490ed'


def resolve_audio():
    hosts = {('Darwin', 'arm64'): 'macos aarch64', ('Linux', 'x86_64'): 'linux x86_64'}
    target = hosts.get((platform.system(), platform.machine()))
    if target is None:
        raise ValueError('Audio replay requires a supported bundled host')
    return _component('audio', 'dobe-audio 0.20.1 ('+target+')', AUDIO_LOCK)


def resolve_photo():
    return _component('photo', 'dobe-photo 0.21.1',
                      'fa60909684a366e3102a0d6390b26b89c31232c0bdb43a39c17292f3834ef7c8')


def resolve_video():
    return _component('video', 'dobe-video 0.20.1',
                      '0a01a1812d9c2295f1c56cbeedf703f576894753fad93f13aa23fd833c470026')


def resolve_motion():
    return _component('motion', 'dobe-motion 0.24.1',
                      '6fda0b9b404bb82deb90651ad17b81baaa959008e70f8f45cc541b5db1026bdf')
