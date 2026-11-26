#!/usr/bin/env bash
# Builds q65lab (Linux) or q65lab.exe (Windows, MSYS2 MINGW64 shell) from the WSJT-X v3.0.2 sources.
#   decoder/q65lab/build.sh <wsjtx source tree> <output folder>
# Needs gfortran, gcc, FFTW3 single precision (libfftw3f) and patch. Windows: pacman -S mingw-w64-x86_64-gcc-fortran
# mingw-w64-x86_64-fftw patch. The result is linked statically, so it runs without extra DLLs.
set -euo pipefail
SRC=$(cd "$1" && pwd)
OUT=$(mkdir -p "$2" && cd "$2" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
W="$OUT/work"
rm -rf "$W" && mkdir -p "$W" && cp -r "$SRC/lib" "$W/lib"
(cd "$W" && patch -p1 --forward < "$HERE/q65lab.patch")
L="$W/lib"
FSRC="prog_args.f90 types.f90 timer_module.f90 fftw3mod.f90 packjt.f90 77bit/packjt77.f90 qra/q65/q65_encoding_modules.f90
 qra/q65/q65.f90 db.f90 four2a.f90 ana64.f90 chkcall.f90 ft8/ft8apset.f90 qra/q65/genq65.f90 indexx.f90 pctile.f90
 qra/q65/q65_ap.f90 qra/q65/q65_loops.f90 qra/q65/q65_set_list.f90 qra/q65/q65_set_list2.f90 q65_decode.f90
 grid2deg.f90 deg2grid.f90 fmtmsg.f90 sec0.f90 shell.f90 smo121.f90 spec64.f90 twkfreq.f90"
CSRC="qra/q65/npfwht.c qra/q65/pdmath.c qra/q65/q65.c qra/q65/q65_subs.c qra/q65/qra15_65_64_irr_e23.c qra/q65/qracodes.c"
FFLAGS="-O2 -fno-second-underscore -fbounds-check -funroll-all-loops -fno-f2c -ffpe-summary=none -I$L"
cd "$W"
OBJ=""
for f in $CSRC; do o="$W/$(basename "$f" .c)_c.o"; gcc -O2 -c "$L/$f" -o "$o"; OBJ="$OBJ $o"; done
for f in $FSRC; do o="$W/$(basename "$f" .f90).o"; gfortran $FFLAGS -c "$L/$f" -o "$o"; OBJ="$OBJ $o"; done
gfortran $FFLAGS -c "$HERE/q65lab.f90" -o "$W/q65lab_main.o"
EXE=q65lab
LDX=""
case "$(uname -s)" in MINGW*|MSYS*) EXE=q65lab.exe; LDX="-static";; esac
ar rcs "$W/libq65lab.a" $OBJ
gfortran $LDX -o "$OUT/$EXE" "$W/q65lab_main.o" "$W/libq65lab.a" -lfftw3f
echo "built $OUT/$EXE"
