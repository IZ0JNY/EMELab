# Q65 Lab — decoder sperimentale / experimental decoder

`q65lab.exe` is the Q65 decoder of **WSJT-X v3.0.2** (© Joe Taylor K1JT and the WSJT Development Group,
GPLv3, <https://github.com/WSJTX/wsjtx>), driven from EMELab's «Q65 Lab» tab. It is **not WSJT-X** and is not
endorsed by its authors.

What is changed (see `q65lab.patch`): three knobs in `lib/qra/q65/q65.f90`, whose defaults keep the WSJT-X
behaviour exactly.

| Knob | WSJT-X | Q65 Lab, wide spread (24 GHz and up) |
| --- | --- | --- |
| `FADE` fading model of the metric | 1 Lorentzian | 0 Gaussian |
| `SMO` spectral smoothing, % | 100 | 200–300, from the expected spread |
| `NTC` averaging time constant | 4 periods | linear average |

Simulated gain (EMELab study, Nov 2026): about +1 dB at 24 GHz Q65-60E with a Moon-like spread of 250 Hz; none at
10 GHz; +0.5 dB with averages of 12–16 periods.

Build: `decoder/q65lab/build.sh <wsjtx v3.0.2 source tree> <output folder>` (Linux, or the MSYS2 MINGW64 shell on
Windows with gcc-fortran and fftw). `q65lab.f90` documents the stdin/stdout protocol.

License: GPL-3.0-or-later, like WSJT-X and EMELab. The complete corresponding source is this folder plus the
WSJT-X v3.0.2 tag.
