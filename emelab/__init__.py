# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EMELab: EME planning, measurements and analysis from 10 to 134 GHz (companion program of FeedLab).

astro    Sun and Moon positions (ERFA/SOFA), distance, Doppler, libration spread, sun–moon angle
atmos    gaseous attenuation (ITU-R P.676 Annex 2) and sky noise from surface weather
sky      Sun and Moon brightness, beam filling, expected Y-factors
link     EME path loss and own-echo SNR
db       local SQLite database of setups and measurements (UTC timestamps)
weather  Open-Meteo and a personal Meteotemplate station (address kept only in the local settings)
analysis measured vs expected, derived G/T, pointing offsets, trends
planner  Moon windows, mutual windows with another station, best days
"""

__version__ = "0.1.18"
