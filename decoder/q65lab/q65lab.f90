! SPDX-License-Identifier: GPL-3.0-or-later
! Q65 Lab: the experimental Q65 decoder of EMELab.
!
! It is the Q65 decoder of WSJT-X v3.0.2 (Copyright (C) 2001-2025 by Joe Taylor K1JT and the WSJT Development
! Group, GPLv3), driven from the command line with three extra knobs (see q65lab.patch): the fading model of the
! metric, the amount of spectral smoothing and the averaging time constant. It is NOT WSJT-X and is not
! endorsed by its authors.
!
! It reads commands from standard input, one per line, and keeps the averaging state between them:
!   SET FADE <0|1>        fading model, 0 Gaussian, 1 Lorentzian (WSJT-X)
!   SET SMO <percent>     spectral smoothing, 100 = WSJT-X
!   SET NTC <n>           averaging time constant in sequences, 4 = WSJT-X
!   CLEAR                 clear the averages before the next decode
!   DECODE <wav> <hhmm> <TRs> <submode A-E> <rx Hz> <ftol Hz> <depth> <mycall|-> <dxcall|-> <dxgrid|-> <maxdrift>
!          <emedelay 0|1> <average 0|1>
!   QUIT
! and writes one line per decode
!   D <hhmm> <snr> <dt> <freq> <q> <nused> <message>
! then "E <navg even> <navg odd> <ms>" when the decode is over ("E ERR <text>" if the file cannot be read).
! The sync curve of the last decode (frequency, average, this period) goes to q65lab_red.dat in the current folder.

module q65lab_cb
  use q65_decode
  implicit none
contains
  subroutine q65lab_decoded(this,nutc,snr1,nsnr,dt,freq,decoded,idec,nused,ntrperiod)
    class(q65_decoder), intent(inout) :: this
    integer, intent(in) :: nutc
    real, intent(in) :: snr1
    integer, intent(in) :: nsnr
    real, intent(in) :: dt
    real, intent(in) :: freq
    character(len=37), intent(in) :: decoded
    integer, intent(in) :: idec
    integer, intent(in) :: nused
    integer, intent(in) :: ntrperiod
    if(idec.lt.0) return
    write(*,'(a,i4.4,i5,f6.2,f9.1,i3,i4,1x,a)') 'D ',nutc,nsnr,dt,freq,idec,nused,trim(decoded)
    call flush(6)
  end subroutine q65lab_decoded
end module q65lab_cb

program q65lab
  use q65lab_cb
  use q65, only: q65x_fade, q65x_smo, q65x_ntc
  use prog_args
  implicit none
  integer, parameter :: NMAX=300*12000
  integer*2, allocatable :: iwave(:)
  character(len=600) :: line, wav
  character(len=16) :: cmd, key
  character(len=12) :: mycall, hiscall
  character(len=6) :: hisgrid
  character(len=1) :: csub
  integer :: ios, nutc, ntr, nfqso, ntol, ndepth, maxdrift, ieme, iavg, nsub, navg0, nqf(20), npts, n
  integer :: c0, c1, crate
  real :: emedelay
  logical :: lclearave, single_decode, lagain, lnewdat, lapcqonly
  type(q65_decoder) :: dec

  allocate(iwave(NMAX))
  lclearave=.true.
  data_dir='.'
  temp_dir='.'
  open(17,file='q65lab_red.dat',status='unknown')
  do
     read(*,'(a)',iostat=ios) line
     if(ios.ne.0) exit
     line=adjustl(line)
     if(len_trim(line).eq.0) cycle
     read(line,*,iostat=ios) cmd
     if(cmd.eq.'QUIT') exit
     if(cmd.eq.'CLEAR') then
        lclearave=.true.
        write(*,'(a)') 'E OK'
        call flush(6)
        cycle
     endif
     if(cmd.eq.'SET') then
        read(line,*,iostat=ios) cmd, key, n
        if(ios.eq.0 .and. key.eq.'FADE') q65x_fade=max(0,min(1,n))
        if(ios.eq.0 .and. key.eq.'SMO') q65x_smo=max(10,min(1000,n))
        if(ios.eq.0 .and. key.eq.'NTC') q65x_ntc=max(1,min(100000,n))
        write(*,'(a,3i7)') 'E SET',q65x_fade,q65x_smo,q65x_ntc
        call flush(6)
        cycle
     endif
     if(cmd.ne.'DECODE') then
        write(*,'(a)') 'E ERR unknown command'
        call flush(6)
        cycle
     endif
     read(line,*,iostat=ios) cmd, wav, nutc, ntr, csub, nfqso, ntol, ndepth, mycall, hiscall, hisgrid, &
          maxdrift, ieme, iavg
     if(ios.ne.0) then
        write(*,'(a)') 'E ERR bad DECODE line'
        call flush(6)
        cycle
     endif
     if(mycall.eq.'-') mycall=' '
     if(hiscall.eq.'-') hiscall=' '
     if(hisgrid.eq.'-') hisgrid=' '
     nsub=ichar(csub)-ichar('A')
     if(nsub.lt.0 .or. nsub.gt.4 .or. (ntr.ne.15 .and. ntr.ne.30 .and. ntr.ne.60 .and. ntr.ne.120 &
          .and. ntr.ne.300)) then
        write(*,'(a)') 'E ERR bad mode'
        call flush(6)
        cycle
     endif
     npts=ntr*12000
     call read_wav(trim(wav),iwave,npts,ios)
     if(ios.ne.0) then
        write(*,'(a)') 'E ERR cannot read wav'
        call flush(6)
        cycle
     endif
     if(iavg.ne.0) ndepth=ior(ndepth,16)
     emedelay=0.
     if(ieme.ne.0) emedelay=2.5
     single_decode=.false.
     lagain=.false.
     lnewdat=.true.
     lapcqonly=.false.
     navg0=0
     nqf=0
     call system_clock(c0,crate)
     call dec%decode(q65lab_decoded,iwave,1,nutc,ntr,nsub,nfqso,ntol,ndepth,200,4000,lclearave,     &
          single_decode,lagain,maxdrift,lnewdat,emedelay,mycall,hiscall,hisgrid,0,0,lapcqonly,navg0,nqf)
     lclearave=.false.
     call system_clock(c1)
     write(*,'(a,2i6,i8)') 'E ',navg0/1000,mod(navg0,1000),nint(1000.0*(c1-c0)/max(1,crate))
     call flush(6)
  enddo

contains

  subroutine read_wav(path,iw,npts,ios)
! 16-bit mono PCM at 12000 Hz: finds the "data" chunk, zero-pads a short file.
    character(len=*), intent(in) :: path
    integer*2, intent(inout) :: iw(:)
    integer, intent(in) :: npts
    integer, intent(out) :: ios
    character(len=4) :: id
    integer*4 :: nsize, nrate
    integer*2 :: nfmt, nch, nbits
    integer :: pos, nread
    iw(1:npts)=0
    open(10,file=path,access='stream',status='old',form='unformatted',iostat=ios)
    if(ios.ne.0) return
    read(10,pos=1,iostat=ios) id
    if(ios.ne.0 .or. id.ne.'RIFF') goto 90
    pos=13
    nrate=0
    do
       read(10,pos=pos,iostat=ios) id, nsize
       if(ios.ne.0) goto 90
       if(id.eq.'fmt ') then
          read(10,pos=pos+8,iostat=ios) nfmt, nch
          read(10,pos=pos+12,iostat=ios) nrate
          read(10,pos=pos+22,iostat=ios) nbits
          if(nfmt.ne.1 .or. nch.ne.1 .or. nrate.ne.12000 .or. nbits.ne.16) then
             ios=2
             goto 90
          endif
       else if(id.eq.'data') then
          if(nrate.eq.0) then
             ios=3
             goto 90
          endif
          nread=min(npts,nsize/2)
          read(10,pos=pos+8,iostat=ios) iw(1:nread)
          goto 90
       endif
       pos=pos+8+nsize+mod(nsize,2)
    enddo
90  close(10)
  end subroutine read_wav

end program q65lab
