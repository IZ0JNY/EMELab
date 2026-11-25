# Equation dossier: OE2IGL / DF3GJ "EME Link Budget & Analysis Tool (1–300 GHz)"

Source analysed: `EMELinkBudget-new.js` (8090 lines, `ver = "v261106"`, header "Libration offset RMS correction (2D) – 2026-10-24"), `EME.html` (page header "v261024"), `MoonGlobe.js`, `JKMap.js`, `lat0.js … lat80.js`.
Authors of the original tool: Gerald Ihninger OE2IGL (2023–2025/26) and Joachim Köppen DF3GJ (2018, 2022). Libration and Q65 threshold work credited in the code to Charlie Suckling DL3WDG.

Purpose of this document: a complete description of every physical model, so that EMELab can re-implement it independently. Formulas are written mathematically. Line numbers refer to `EMELinkBudget-new.js` unless stated otherwise. "Code:" means "this is literally what the code does", even where it looks physically odd. Points I could not resolve are marked **UNCLEAR**. Suspected defects are marked **BUG?** and collected again in §13.

Notation:

- `ln` is the natural log, `lg` = log10.
- Angles are in degrees unless marked [rad]. The code's `ARC = π/180` (l.9).
- `dB(x) = 10·lg(x)`.
- "TX" and "RX" refer to the transmitting and receiving stations. Most formulas exist twice, once with the `tx` prefix and once with `rx`.

---

## 0. Global constants and conventions (l.8–60)

| Name | Value | Meaning |
|---|---|---|
| `ARC` | π/180 | deg→rad |
| `M10` | 1/ln 10 | used by `log10(x) = M10·ln x` (l.3732) |
| `HPBW0` | 180/π = 57.2958 | "beam constant" in degrees per radian. The comment says the 1.029 factor of a uniform aperture is inside the beam-factor formula, so this is 57.296 and not 58.957. |
| `ARCS` | ARC/3600 | arcsec→rad |
| `REFCON` | 0.015 | scale of the optical refraction formula |
| `REARTH` | 6378.137 km | Earth equatorial radius |
| `CLIGHT` | 299792.0 km/s | declared, not used in the physics |
| `tandelta` | 0.0143 | loss tangent of the lunar regolith (thermal-emission model) |
| `eps` | 1.5 | relative permittivity of the regolith (thermal-emission model). Note that `libration()` has a local `eps` (obliquity) that shadows it. |
| `deltaT` | 70 s | TT − UT, added to the time in the Sun/Moon ephemerides |
| `rmoon` | 1737.4 km | lunar radius |
| `emoon` | 0.075 (initial) | lunar reflectivity ε (§3) |
| `txaddloss`, `rxaddloss` | −0.025 | added (not multiplied) to the maximum Gaussian efficiency (§10) |
| `librate` | 0.002 | declared, not used |
| `K[]` | [46.625, 45.375, 4.1572, 1.4468, 0.25391, 2.2716, −1.3465, −4.3877, 3.1484, 4.5201, −1.8982, 0.89] | Berman–Rockwell refraction coefficients (§8) |

Wavelength (l.966): `wave = λ[m] = 0.3/f[GHz]`. The code uses 0.3, not 0.299792.

Valid frequency input (l.961): 1 < f ≤ 350 GHz. The title says 1–300 GHz.

Month convention: the `month` variable is 0-based (0 = Jan), as in the HTML select. `libration()` uses `month+1`.

Program flow:

1. `readFields()` (l.882) validates the inputs and derives a few quantities: mesh efficiency, gain, and the reflectance normalisation.
2. `compute()` (l.1803) runs everything else:
   - optional locked elevations;
   - `compute1()`, the ephemerides;
   - dish efficiencies and HPBW;
   - `computeIntegrals()`;
   - path loss, atmosphere, noise temperatures, S/N, libration and thresholds.

---

## 1. Beam profiles and HPBW conventions

### 1.1 `profile(shape, hpbw, r)` (l.1447–1475)

Normalised power pattern P(r), with P(0) = 1. `r` is the angular distance from the beam axis in degrees and `hpbw` is the full half-power beam width in degrees. For r < 0.001° the function returns 1.

| shape | Formula | Note |
|---|---|---|
| `e` (evenly illuminated circular dish, Airy) | u = π·sin(r·π/180)·(HPBW0·1.029/hpbw); P = [2·J1(u)/u]² | The Airy argument is u = π(D/λ)sin r, with D/λ eliminated through hpbw = 1.029·HPBW0·λ/D. P therefore has its half-power points at r = hpbw/2. |
| `t` (top hat) | P = 1 if r < hpbw/2, else 0 | not offered in the HTML |
| `g` (Gaussian) | h = 2.3548·r/hpbw; P = exp(−h²/2) | σ = hpbw/2.3548 (2.3548 = 2√(2 ln 2)) |
| `x` ("data from feed/dish simulation") | identical to `g` | Only the efficiencies and HPBW differ (§10). |
| `s` (sinc²) | h = 2.7831·r/hpbw; P = [sin h / h]² | 2.7831 = 2·1.39156 (sinc² half-power point). Not offered in the HTML. |
| `z` | P = 1 for r < hpbw/2.25; P = sqrt(1e-4·exp(ln(r/(2·hpbw))·ln(1e-4)/ln(4.5))) = sqrt(1e-4·(r/(2hpbw))^(ln 1e-4/ln 4.5)) for hpbw/2.25 ≤ r < 2·hpbw; P = 0 for r ≥ 2·hpbw | Continuous at r = hpbw/2.25 (P = 1); P = 0.01 at r = 2·hpbw, then a jump to 0. Not offered in the HTML. |

The HTML offers only `e`, `g` (default) and `x` for both stations. Their labels are "evenly illum.circular dish", "Gauss, max ant. η = theor.-2.5%" and "data from feed/dish simulation".

Bessel J1 (`Bessel()`, l.834–880; Numerical Recipes `bessj1`):

- For |x| < 8: J1(x) = x·(r1 + y(r2 + y(r3 + y(r4 + y(r5 + y·r6))))) / (s1 + y(s2 + y(s3 + y(s4 + y(s5 + y·s6))))), with y = x²:
  - r1..r6 = 72362614232.0, −7895059235.0, 242396853.1, −2972611.439, 15704.48260, −30.16036606
  - s1..s6 = 144725228442.0, 2300535178.0, 18583304.740, 99447.43394, 376.9991397, 1.0
- Otherwise, with z = 8/|x|, y = z² and xx = |x| − 2.356194491:
  J1 = sign(x)·sqrt(0.636619772/|x|)·[cos(xx)·(p1 + y(p2 + y(p3 + y(p4 + y·p5)))) − z·sin(xx)·(q1 + y(q2 + y(q3 + y(q4 + y·q5))))]
  - p = 1.0, 0.183105e-2, −0.3516396496e-4, 0.2457520174e-5, −0.240337019e-6
  - q = 0.04687499995, −0.2002690873e-3, 0.8449199096e-5, −0.88228987e-6, 0.105787412e-6

### 1.2 Beam-shape factor and HPBW (l.2143–2157 TX, l.2334–2347 RX)

Edge taper T_e [dB] is an input, valid range −30 … 0 dB.

- Amplitude ratio (computed, not used further): `txet = 10^(T_e/20)`.
- Beam-broadening factor ("gaussian", l.2146/2336):

  bf(T_e) = 1.841e-6·T_e³ + 0.00019683·T_e² − 0.0096337·T_e + 1.029

  At T_e = 0 this gives bf = 1.029. The commented-out alternative is Baars' quadratic-on-pedestal: 1.269 − 0.566·et + 0.534·et² − 0.208·et³.
- HPBW for shape `g`: θ = bf·HPBW0·λ/D [deg].
- HPBW for any other shape (`e`, `x`): θ = sqrt( 34306 / ( (πD/λ)²·η_i,sim² ) ) [deg], where η_i,sim is the "sim illumination efficiency" input (`txsimilleff`/`rxsimilleff`).
  - 34306 ≈ (185.22)²: with η = 1 this gives θ = 58.96·λ/D.
  - **Code:** the square uses η_i,sim·η_i,sim. The comment talks about η_i·η_s, so see §13.
  - For shape `e`, the hidden field `*similleff` is used. Its HTML default is 1, but the presets also set it.
- A yellow warning appears if θ > 20° or θ < 0.01°.
- The HPBW does not depend on the "used efficiency" η_real (`txeff`). A commented-out version did.
- Convolution width (display only; also used to decide whether beam circles are drawn; l.2352):
  θ_conv = sqrt( θ_rx²·θ_tx² / (θ_rx² + θ_tx²) ).
- The RX Gaussian σ for the thermal-noise integral (l.2350–2351): σ = θ_rx/2.3548 and `sigma2` = 2σ².

### 1.3 Gain from the "used" efficiency (readFields l.1087–1088, l.1299–1300)

Ω_A = 4·(λ/(D·sqrt(η_real)))²/π [sr] and G = 4π/Ω_A = η_real·(πD/λ)².

Here η_real is `txeff`/`rxeff`, the input "Used ant. effi. η real", valid range 0…1. This is the only gain used in the link budget. Every computed efficiency in §10 is for display only.

---

## 2. Moon-disc integrals (`computeIntegrals`, l.1478–1576; `normtx`/`normrx`/`normReflect`, l.1411–1445; results in `compute`, l.2358–2385)

### 2.1 Grid

The grid is a square sky-plane raster centred on the Moon centre, with angular coordinates x, y in degrees.

- amax = 0.3°.
- np = 125 normally, 50 if `imageMode == "beamtempmap"`, and 80 in the live/auto-step modes (`timer == 1`). `nxs = nys = np` is also used later by `calcMoonTemp`.
- dr = 2·amax/np, and x_i = −amax + i·dr, y_j = −amax + j·dr for i, j = 0 … np−1.
  - **Note:** the grid runs from −0.3 to 0.3 − dr. It is not symmetric about 0 (§13).
- The cell area is dr².
- The flat-sky small-angle approximation is used: r = sqrt(x² + y²).
- The Moon radius is a_moon = `armoon` = diam/2, where diam is the geocentric angular diameter (§9.5).

### 2.2 Pointing offsets

TX beam centre: (x_tx, y_tx) = (`txxpos`, `txypos`). RX beam centre: (x_rx, y_rx). The inputs are "Position x,y on Moon [°]", each in −0.5…0.5, default 0.

For each cell:

- P_tx(x, y) = profile(tx shape, θ_tx, sqrt((x−x_tx)² + (y−y_tx)²)) if r ≤ a_moon, else 0 ("bright").
- P_tx,ref = the same with zero offset ("brightref").
- P_rx(x, y) = profile(rx shape, θ_rx, sqrt((x−x_rx)² + (y−y_rx)²)), evaluated everywhere on the grid ("h").
- P_rx,ref = the same with zero offset ("href").
- If `reflectMode == "r"` (radial reflectance), both P_tx and P_tx,ref are multiplied by ρ̂(r) = R(f, r/a_moon)/N_R, where R is defined in §3 and N_R = `reflectNorm`. The code has a separate branch for r ≤ 0.05° that multiplies by `1.0*…`, which is identical. Otherwise (`"c"`) the reflectance is uniform and no factor is applied.

### 2.3 Sums (multiplied by dr² at the end)

| Sum | Definition | Used for |
|---|---|---|
| S_tx (`sumtx`) | Σ P_tx, taken **before** the reflectance factor | intercepted power, illuminated fraction |
| S_rx1 (`sumrx1`) | Σ P_tx·P_rx, without reflectance | unused |
| S_rx (`sumrx`) | Σ P_tx·ρ̂·P_rx | BWF |
| S_rx,ref (`sumrxref`) | Σ P_tx,ref·ρ̂·P_rx,ref | BWF with zero offsets |
| S_moon (`summoon`) | Σ_{r ≤ a_moon} P_rx | RX Moon fill |
| S_sun (`sumsun`) | Σ_{r ≤ a_sun} P_rx | RX Sun fill. The Sun disc is assumed centred where the Moon centre is, and the same RX offsets are used. |
| S_cmb (`sumcmd`) | Σ_{r > a_moon} P_rx | computed, unused |
| moments | §5.4, for r ≤ a_moon: weights w = P_tx·ρ̂·P_rx (current) and w_ref = P_tx,ref·ρ̂·P_rx,ref | libration width, Q65 |

### 2.4 Beam normalisations

- `normtx()` = ∫₀^{3θ_tx} r·P_tx(r) dr, computed with a rectangle sum of n = 1000 steps (dr = 3θ/n, i = 1…999).
- `normrx()` is the same for RX.
- 2π·norm is the beam solid angle in deg², integrated to 3·HPBW in the flat-sky approximation.

### 2.5 Derived factors (`compute`, l.2358–2385)

With A_moon = π·a_moon² [deg²]:

- Intercepted power fraction (TX fill factor): F_tx = S_tx / (2π·normtx). Display `txpwr`, linear and in dB.
- RX fill factor, Moon: F_moon = S_moon / (2π·normrx) (`rxfillmoon`, display `overlap`).
- RX fill factor, Sun: F_sun = S_sun / (2π·normrx) (`rxfillsun`).
- Illuminated fraction: I = S_tx / A_moon (`illu`).
- Beam Width Factor: BWF = S_rx / A_moon (the variable `sumrx` is overwritten). BWF_ref = S_rx,ref / A_moon.
- HTML definitions: BWF = ∫Φ_TX Φ_RX dx dy / (πR²_moon), and the split BWF = illuminated · beam_overlap, with beam_overlap = ∫Φ_TX Φ_RX / ∫Φ_TX.
  - The code does not output beam_overlap separately. The field labelled "RX fill factor moon" (`overlap`) shows F_moon; the version that showed S_rx1/S_tx is commented out.
- CMB: the Moon blocks the CMB over the fraction F_moon of the RX beam. This enters as T_cmb·(1 − F_moon) in the on-Moon noise terms (§4.6). For the Sun it is (1 − F_sun).

### 2.6 `normReflect()` (l.1411–1420)

N_R = 2·Σ_{i=1}^{999} r_i·R(f, r_i)·Δr, with Δr = 1/1000 and r_i = i·Δr.

This is the disc-average of R over the normalised radius (2∫₀¹ r R dr). As a result, ρ̂ = R/N_R has unit disc average and the BWF is unchanged on average. `readFields` computes it at every call (l.1406).

---

## 3. Lunar reflectance and reflectivity choices

### 3.1 `getReflectance(f, x)` (l.1792–1800, "J. Koeppen (2022)")

f is in GHz and x = r/a_moon ∈ [0, 1] is the normalised radius on the disc.

- b1 = max(0, 100 − 60·lg f)
- b2 = 40 + 10·exp(−f/2)
- a2 = 10^(−2.5 − 12·exp(−f))
- c = 7·exp(−f/20)
- d = 25 + 10·exp(−f/20)
- R(f, x) = 10^( [ lg( exp(−b1·x) + a2·exp(−b2·x) ) − c·x^d ] / 10 )

Equivalently R = (e^(−b1 x) + a2 e^(−b2 x))^(1/10) · 10^(−c·x^d/10). R(f, 0) = (1 + a2)^0.1 ≈ 1.

Behaviour:

- At low frequency R is strongly peaked at the centre (quasi-specular).
- Above about 40 GHz, b1 = 0, so R ≈ 1 except for the limb term c·x^d.
- The HTML says the radial model is derived from Fig. 10 in Evans (1969) and other works.
- Reference values (computed from the formula above): §12.

### 3.2 Radial vs constant (`reflect` select, l.1529–1535)

- `"r"`: "Lunar reflectivity varies radially". This is the default set in `window.onload`, although the HTML text says constant is the default.
- `"c"`: "constant across lunar disc".

The choice only changes the weighting inside the BWF and moment integrals (§2.2). The normalisation N_R keeps the mean equal to 1. The total reflectivity is always ε (`emoon`).

### 3.3 Reflectivity ε (`reflmoon` select, `handleReflmoon` l.7279–7297; `readFields` l.986–991)

| Option | ε |
|---|---|
| `d` default (average) — the default | 0.075 |
| `m` maria | 0.11 |
| `h` highlands | 0.055 |
| `c` craters | 0.13 |
| `e` enter reflectivity | user value in [0, 1] (field `emoon`) |

The HTML general text quotes ε ≈ 0.07. ε enters the radar equation linearly (§4.2).

---

## 4. Radar equation, path loss, echo power, noise and S/N chain (`compute`, l.1803–2905)

### 4.1 Elevations used

The `elelock` select controls where the elevations come from:

- `n` ("NO, set elevation manually"): the elevations are inputs. TX elevation range is 0.1…90°; RX elevation range is 0.1…180°, where values above 90° mean "over the zenith" and are used in the spillover model. Default 30°/30°.
- `m` (Moon) and `s` (Sun): the elevations are computed for each station. `compute1()` is called with that station's lat/long, and the result is the true (airless) topocentric elevation `elmoonsim`/`elsunsim` plus the radio refraction `GetRefractionRadio(el_true, T, RH, P)` of §8.1:
  - E_tx = el_true,tx + τ_radio(el_true,tx, T_tx, RH_tx, P_tx), and the same for RX;
  - the azimuth is the computed azimuth.
- **Note:** `window.onload` sets `$("#elelock").val("0")`, which is not one of the options, so on first load `elelock` is neither `n`, `s` nor `m`. The elevations then keep their initial values of 30°. **UNCLEAR**/§13.

### 4.2 Isotropic path loss and the received signal (l.2389–2425)

- h = λ·R_m / (8π·d²), with λ in m, R_m = 1737.4·1000 m and d = `dmoon`·1000 m.
- `dmoon` = mean topocentric distance from the two stations to the near lunar surface (§9.4).
- L_path = h² is the HTML formula (R_moon λ/(8π d_TX d_RX))², with d_TX = d_RX = d.
- Corrected path loss: L_corr = L_path·BWF.
- Gains product shown: ε·G_tx·G_rx.
- Atmospheric loss:
  - A_zen,tx = attenuation2(T_tx, RH_tx, P_tx) + cloudloss_tx [dB] (§7);
  - A_los,tx = A_zen,tx / sin(E_tx) (plane-parallel cosecant law, no Earth curvature);
  - the same for RX, plus the RX transmission τ_rx = 10^(−A_los,rx/10) (`rxexpo`).
- Received signal power [mW]:

  P_sig = P_tx[W]·1000 · 10^(−A_los,tx/10) · G_tx · G_rx · ε · L_path · BWF · τ_rx

- What is **not** in P_sig:
  - polarisation loss, which is only displayed (§4.9);
  - pointing loss, except through the beam offsets inside BWF;
  - Ruze or any of the efficiencies of §10, except through the user's η_real in G;
  - a separate TX feed loss.

### 4.3 Receiver noise (l.2430–2440)

- Noise-power conversion: k_B·B = 1000·1.38e-23·B[kHz]·1000 [mW/K] (`temp2mW`). Here k = 1.38e-23. B = `rxbw` [kHz], default 2.5, range (0, 100]. `handleDecode` forces B = 2.5 for every mode.
- T_rx = 290·(10^(NF/10) − 1) [K]. NF in dB, range (0, 100], HTML default 0.7; the RX preset 1 sets 0.72.
- Main-beam efficiency (l.2436): η_MB = 0.8899·bf_rx²·η_real,rx (`eta`). 0.8899 = 1.1331·π/4, i.e. Ω_MB/Ω_A for a Gaussian main beam of width bf·λ/D.
- Forward efficiency η_F (`etaf`) is set by the RX shape (l.2207, 2253, 2302, 2330) and **overrides** the input field `rxetaf`:
  - `g` → 0.85;
  - `e` → 1.0;
  - `x` → η_s,sim,rx − 0.02;
  - other → 0.85.
  The value is written back to the field. The variable `rxetaf` read in `readFields` is never used.
- Simple S/N (field `snr`): P_sig / (k_B·B·T_rx).
- N_rx [dBm] = dB(k_B·B·T_rx).

### 4.4 Sky and CMB temperatures (l.2415–2445)

- Mean radiating temperature of the atmosphere: T_m = 0.81·(273.15 + T_rx,°C) + 37.4 [K].
- T_sky,zen = T_m·(1 − 10^(−A_zen,rx/10)).
- T_sky(E) = T_m·(1 − τ_rx) (`skytemp`).
- T_sky,45 = T_m·(1 − 10^(−A_zen/(10 sin 45°))), computed but unused.
- CMB, Planck brightness of 2.73 K attenuated by the atmosphere at the current elevation:

  T_cmb = (hν/k)/(exp(hν/(k·2.73)) − 1)·τ_rx, with h = 6.626e-34, k = 1.3806e-23 and ν = f·1e9.

  The zenith display uses τ_zen instead of τ_rx. In the zenith formulas of §4.6 the code reuses T_cmb computed with τ_rx, not τ_zen (§13).
- Displays: `skytemp` = T_sky + T_cmb, and `skytempzenith` = T_sky,zen + T_cmb,zen.

### 4.5 Spillover temperature (l.2447–2513)

Inputs:

- θ0 = half opening angle "dish centre – rim" (`rxcenter2rim`, §10.2);
- ψ_t = feed tilt: 0 for a prime-focus dish (offset angle = 0), and for an offset dish ψ_t = θ0 (the same expression, l.2184);
- E = RX elevation;
- T_g = 273.15 + T_rx,°C, the ground temperature, equal to the ambient air temperature.

Ground-seeing fraction ("spillfactor"): the uniform mean over the integer cone half-angles i = round(θ0) … 89 (degrees):

s_i = 1 − arccos( tan(e′)/tan(i) )/π if e′ < i, else 1,

s = (Σ s_i)/(90 − round(θ0)).

The effective axis elevation e′ depends on the case:

- E ≤ 90: e′ = E − ψ_t;
- E > 90 and prime focus: e′ = 180 − E − ψ_t;
- E > 90 and offset: e′ = E − ψ_t (the code is literally identical to the E ≤ 90 branch).

Interpretation (not stated in the code): s_i is the fraction of a cone of half-angle i around the feed's spillover axis that lies below the horizon.

Sky temperature seen by the spillover:

- A_spill = A_zen / sin(E + (180 − θ0)/2) for E ≤ 90;
- A_spill = A_zen / sin(180 − E + (180 − θ0)/2) for E > 90;
- T_sky,spill = T_m·(1 − 10^(−A_spill/10)).

Spillover temperature: T_spill = s·T_g + (1 − s)·T_sky,spill. For RX shape `e` the code sets T_spill = 0.

Zenith spillover (for the Y-factor calibration):

- prime focus: T_spill,zen = T_g;
- offset: the same loop with e′ = 90 − ψ_t, and the sky part T_m·(1 − 10^(−A_zen/(10·sin(90 + (180 − θ0)/2)))).

Horizon spillover (dish pointing at E = 0, used in the "gnd" Y-factor):

- s0 = 1 − arccos( tan(−ψ_t)/tan θ0 )/π;
- T_spill,0 = s0·T_g + (1 − s0)·T_sky(E). The code uses the current-elevation sky temperature T_sky, not a horizon value.

Additional spillover T_add (`addspillovertemp`, input range −270…200 K, default 0) is added wherever written below.

Displayed "RX antenna noise temp." (l.2561): (1 − η_F)·(T_spill + T_add) + η_F·(T_sky + T_cmb).

### 4.6 System temperatures and Y-factors (l.2563–2588)

With η = η_MB, η_F, T_rx and the RX side only:

| Quantity | Formula |
|---|---|
| abs (absorber in front of the feed) | T_g + T_rx |
| gnd (feed in dish, pointing at ground) | η_F·T_g + (1 − η_F)·T_spill,0 + T_rx |
| gnd2 (feed only, ground) | 0.997·T_g + 0.003·T_sky,zen + T_rx |
| skyzenith (dish at zenith) | η(T_sky,zen + T_cmb) + (η_F − η)(T_sky,zen + T_cmb) + (1 − η_F)(T_spill,zen + T_add) + T_rx |
| skyzenith2 (feed only, zenith) | 0.997(T_sky,zen + T_cmb) + 0.003·T_g + T_add + T_rx |
| sky (cold sky at elevation E) | η(T_sky + T_cmb) + (η_F − η)(T_sky + T_cmb) + (1 − η_F)(T_spill + T_add) + T_rx |
| sun | η(T_sun + T_sky + T_cmb(1 − F_sun)) + (η_F − η)(T_sky + T_cmb) + (1 − η_F)(T_spill + T_add) + T_rx |
| moon | η(T_moon + T_sky + T_cmb(1 − F_moon)) + (η_F − η)(T_sky + T_cmb) + (1 − η_F)(T_spill + T_add) + T_rx |

Displayed ratios (dB):

- Y_abs,zen = abs/skyzenith
- Y_gnd,zen = gnd/skyzenith
- Y_abs,E = abs/sky
- Y_gnd,E = gnd/sky
- Y_feed = gnd2/skyzenith2
- abs/skyzenith2 (field `absskyfeed`, which does not exist in the HTML)
- **Y-Sun** = sun/sky
- **Y-Moon** = moon/sky

Source terms:

- T_sun = T_☉(f)·F_sun·τ_rx, where T_☉ = `solarTemp(f·1000 MHz)` (§11.1). The displayed field `sfu` shows T_☉ in K.
- T_moon = `calcMoonTemp()`·τ_rx (§6). This is the beam-weighted lunar brightness, including the fill factor through its normalisation.
- Displays:
  - "Rx antenna temp. of moon" (`tbeam`) = T_moon;
  - `moontemp` = "mo*beam" calcMoonTemp();
  - Moon noise [dBm] = dB(η·T_moon·k_B·B).

G/T (l.2591): G/T = 10·lg( G_rx / ( T_moon + T_sky + (η_F − η)·T_sky + (1 − η_F)(T_spill + T_add) + T_rx ) ) [dB/K].

- **Code:** the T_moon and T_sky terms are not multiplied by η, and there is no CMB term (§13).

### 4.7 S/N EME (l.2592–2598)

The libration width factor W = `emeLibWidthFactor` is defined in §5.5. Both S/N values are evaluated only if E_rx > 0 and E_tx > 0; if E_rx > 0 but E_tx ≤ 0, S/N_EME = −99.

S/N_EME = 10·lg( η·P_sig / ( [η(T_moon + T_sky + T_cmb(1 − F_moon)) + (η_F − η)(T_sky + T_cmb) + (1 − η_F)(T_spill + T_add) + T_rx]·k_B·B ) ) − 10·lg W

S/N_EME,2 ("Signal/(0+Sky+Noise)") is the same without T_moon.

- **Code:** the signal is multiplied by η_MB, although G_rx already contains η_real.
- −10·lg W is a gain (W ≤ 1). It models the reduced effective echo bandwidth when narrow beams see only part of the disc.
- The whole noise/S-N block runs only if E_rx > 0 (l.2441). If E_rx ≤ 0, `snrmoon`, `emeLibWidthFactor` and `rxMinus` etc. are undefined; see §13.

### 4.8 Decoder thresholds and margin (l.2738–2900)

The threshold uses the uncorrected mutual libration spread L = `txrxlibspread` [Hz] (§5.2). For 60D and 120E, L is clamped to ≤ 550 Hz.

| Mode | Threshold [dB in 2500 Hz] | Source |
|---|---|---|
| `s` SSB | 6 | fixed |
| `c` CW | 10·lg( 3 / sqrt(B·1000·t_int) ) with t_int = B/2.5/W [s] | 3σ detection ("5× for 100% readability"); for B = 2.5 kHz and W = 1, t_int = 1 s and the threshold is −12.2 dB |
| `60D` Q65-60D | 5.6139e-8·L³ − 6.4781e-5·L² + 3.7718e-2·L − 28.285 | C. Suckling DL3WDG (2022, "EME2020 conference") |
| `60E` Q65-60E (default) | −3.6013e-12·L⁴ + 1.5565e-8·L³ − 2.4829e-5·L² + 0.022733·L − 27.483 | "new curve until 1300 Hz, Apr 2023 C. Suckling" |
| `120E` Q65-120E | 3e-8·L³ − 0.00005·L² + 0.0387·L − 30.751 | DL3WDG |

- **Margin = S/N_EME − threshold.** The field `margin` is green if S/N_EME > threshold.
- For the Q65 modes the **V2.3 research threshold** (§5.6) is also computed and shown in the field `thresholdcorr`. **It is not used in the margin.**

CW with a user integration time t_user > 0 (field `inttime`, seconds):

- x_σ = 10^(S/N_EME/10)·sqrt( B·1000·t_user / W );
- the result is green if x_σ ≥ 3;
- the threshold and margin are hidden in this case.

With t_user = 0 (empty field), the threshold/margin form above is used.

In Sun-lock mode (`elelock == "s"`), signal, S/N and margin are suppressed ("---").

### 4.9 Spatial polarisation (Moon-lock only, l.1927–1946)

For each station (lat φ, Moon azimuth A, elevation E):

pol = arctan[ ( sin φ·cos E − cos φ·cos A·sin E ) / ( cos φ·sin A ) ] [deg]

- Δ = pol_rx − pol_tx, folded into (−90, 90).
- Loss: L_pol = 20·lg cos( Δ·(1 − 0.064·(Δ/90)^10) ) [dB]. The comment says this limits the cross-polar loss at 90° to about −20 dB.
- With ±90° feed rotation: Δ′ = Δ + 90 if Δ ≤ 0, else Δ − 90, and the same loss formula. Display only.

### 4.10 "Search max margin" (auto-step) (`handleAutostep`/`steptime`, l.7664–7765)

This is a time search with the elevations locked to the Moon:

- coarse steps of +30 min, then +5 min while the margin keeps increasing;
- when the margin starts to decrease after a positive maximum, the search steps back 5 min and reports the time (`optdate`).

Live mode (`handleAutoplay`) recomputes every 5 s with the current time. Neither is physics.
---

## 5. Libration, spreading, Doppler, beam correction and the Q65 V2.3 threshold

### 5.1 `libration(deltamin, lat, lon, mode)` (l.2954–3067)

The comment credits Charlie Suckling DL3WDG and https://www.bobatkins.com/radio/g3wdg_libration.html.

Inputs:

- `deltamin`: time shift in minutes, −1 or +1;
- `lat`, `lon`: station geodetic latitude and east longitude in degrees (they shadow the globals);
- `mode` ("rx"/"tx"): only controls the drawing side effects (`MoonGlobe.update`, beam overlays).

The function uses the global UTC date/time `year`, `month` (0-based), `day`, `hour`, `min`. Seconds are ignored and there is no ΔT. It returns `{first: lib_lat, second: lib_lon, pospara}`: the topocentric selenographic latitude and longitude of the sub-observer point in degrees, and the position-angle rotation in rad.

Algorithm. M = month+1, D = day, U = hour + (min + deltamin)/60.

1. Day number from J2000.0:
   d = 367·Y − ⌊7·(Y + ⌊(M+9)/12⌋)/4⌋ + ⌊275·M/9⌋ + D + U/24 − 730531.5.
2. Local sidereal time [rad]:
   LST = (100.46 + 0.985647·d + lon + 1.00273790935·15·U) mod 360.
3. T = d/36525.
4. Fundamental arguments [deg] (taken mod 360 where the code does):
   - M☉ = 357.529 + 35999·T − 0.0001536·T² + T³/24490000
   - ε = 23.43929111 + T·(−46.8150 + T·(−0.00059 + 0.001813·T))/3600
   - F = 93.2721 + 483202·T − 0.003403·T² − T³/3526000
   - L′ = (218.316 + 481268·T) mod 360
   - Ω = 125.045 − 1934.14·T + 0.002071·T² + T³/450000
   - M′ = 134.963 + 477199·T + 0.008997·T² + T³/69700
   - D_e = (297.85 + 445267·T − 0.00163·T² + T³/545900) mod 360
5. Distance factor:
   q_d = 1 + (−20954·cos M′ − 3699·cos(2D_e − M′) − 2956·cos 2D_e)/385000.
   The Moon distance is 385000·q_d km.
6. Geocentric ecliptic latitude:
   β = 5.128·sin F + 0.2806·sin(M′+F) + 0.2777·sin(M′−F) + 0.1732·sin(2D_e − F).
7. Longitude:
   Δλ = 6.289·sin M′ + 1.274·sin(2D_e − M′) + 0.6583·sin 2D_e + 0.2136·sin 2M′ − 0.1851·sin M☉ − 0.1143·sin 2F + 0.0588·sin(2D_e − 2M′) + 0.0572·sin(2D_e − M☉ − M′) + 0.0533·sin(2D_e + M′);
   λ = L′ + Δλ.
8. Equatorial coordinates:
   α = fold( atan2( sin λ·cos ε − tan β·sin ε, cos λ ) );
   δ = asin( sin β·cos ε + cos β·sin ε·sin λ ).
9. Optical libration (Meeus-type):
   - I = 1.54242°, W = (λ − Ω) mod 360;
   - A = atan2( sin W·cos β·cos I − sin β·sin I, cos W·cos β );
   - l_geo = A − F [deg];
   - b_geo = asin( −sin W·cos β·sin I − sin β·cos I ) [deg] (`bo`; also kept in rad as `dummy`).
10. Hour angle: H = LST − α.
11. Position angle of the lunar axis:
    - xx = sin I·sin Ω;
    - yy = sin I·cos Ω·cos ε − cos I·sin ε;
    - ω = atan(xx/yy) if yy > 0, else π + atan(xx/yy);
    - P = asin( sqrt(xx² + yy²)·cos(α − ω) / cos b_geo ) [rad]. In this expression α is recomputed as the un-folded atan2.
12. Parallactic angle:
    q = atan2( cos φ·sin H, cos δ·sin φ − sin δ·cos φ·cos H ), mapped to [0, 2π).
13. Geocentric zenith distance:
    z = acos( sin δ·sin φ + cos δ·cos φ·cos H ).
14. Horizontal parallax: π_h = asin( REARTH / (385000·q_d) ) [deg].
    Topocentric reduction factor: π′ = π_h·( sin z + 0.0084·sin 2z ).
15. Topocentric corrections:
    - Δl = −π′·sin(q − P) / cos(asin(b_geo,rad)). **Code:** this is asin applied to an angle; see §13. The difference from cos b is O(b⁴).
    - Δb = π′·cos(q − P).
16. Results:
    - lib_lat = b_geo + Δb;
    - lib_lon = l_geo + Δl;
    - pospara = (−(P − q) + 2π) mod 2π. This is the rotation from Moon-fixed axes to apparent sky X/Y.
    - Display only: `polzenmoon` = (P − q) in degrees; the screen cross at (175·sin lib_lon, 175·sin lib_lat) rotated by pospara.

`compute` calls `libration` four times (l.2549–2552): RX(−1), RX(+1), TX(−1), TX(+1). That is two samples 2 minutes apart for each station.

### 5.2 Libration rates and spreading (l.2642–2694)

Let (b⁻, l⁻) and (b⁺, l⁺) be the samples at −1 and +1 min, in degrees.

- RX libration rate [°/min]:
  ω_rx = sqrt( (b_rx⁻ − b_rx⁺)² + (l_rx⁻ − l_rx⁺)² ) / 2. No cos(b) factor is applied to Δl.
- RX ("own") spreading: S_rx = 6745.5·f[GHz]·ω_rx [Hz].
  - Not stated in the code: 6745.5 is close to 4·R_moon·(π/180/60)/λ with λ = 0.3/f, which gives 6738.6. This would be the full-disc two-way Doppler width for an apparent rotation rate ω. The literal 6745.5 must be used.
- Mutual: the TX and RX sample positions are averaged before differencing.
  - b̄^∓ = (b_rx^∓ + b_tx^∓)/2, l̄^∓ = (l_rx^∓ + l_tx^∓)/2;
  - ω_mut = sqrt( (b̄⁻ − b̄⁺)² + (l̄⁻ − l̄⁺)² ) / 2;
  - S_mut = 6745.5·f·ω_mut [Hz] (`txrxlibspread`, field "Mutual libr. spread").
- Beam-corrected mutual spread: S_mut,corr = min( S_mut·W, S_mut ) (field `mutallibspreadcorr`).
- Libration plane angle (display): α_l = atan2( b̄⁻ − b̄⁺, l̄⁻ − l̄⁺ ).
- Weighted beam-offset angle: β = atan2( (y_rx·θ_tx² + y_tx·θ_rx²)/(θ_tx² + θ_rx²), (x_rx·θ_tx² + x_tx·θ_rx²)/(θ_tx² + θ_rx²) ).

### 5.3 Doppler offset due to libration (l.2696–2731)

- Clamp the x offsets: x̃ = clamp(x, −diam/2, +diam/2), where diam is the geocentric Moon diameter in degrees.
- f_D,lib = 6745.5·ω_mut·f·( x̃_rx·θ_tx² + x̃_tx·θ_rx² )/(θ_tx² + θ_rx²)·cos(α_l)/diam [Hz].
- The sign is flipped unless α_l − π/2 < β < α_l + π/2.
- Only the x offsets are used. A 2-D version using sqrt(x² + y²)·cos(α_l − β) is commented out.

### 5.4 Echo moments, covariance and gradient angle (l.1579–1636)

Weighted 2-D moments over the Moon grid, accumulated inside `computeIntegrals` for cells with r ≤ a_moon:

- weights w = P_tx·ρ̂·P_rx (`emeLibMoments`) and w_ref = P_tx,ref·ρ̂·P_rx,ref (`emeLibMomentsRef`);
- m = {Σw, Σwx, Σwy, Σwx², Σwy², Σwxy}, with x, y in degrees.

`emeCovariance(m)`: with x̄ = Σwx/Σw and ȳ = Σwy/Σw,

- C_xx = max(0, Σwx²/Σw − x̄²);
- C_yy = max(0, Σwy²/Σw − ȳ²);
- C_xy = Σwxy/Σw − x̄ȳ;
- the result is null if Σw ≤ 0.

`emeDirectionalVariance(C, a)`:

- with u = (cos a, sin a): v = max(0, C_xx·u_x² + 2·C_xy·u_x·u_y + C_yy·u_y²);
- if a is not finite: v = (C_xx + C_yy)/2.

`emeLibrationGradientAngleDeg(rx⁻, rx⁺, tx⁻, tx⁺)`. For each station, with ψ = pospara of the "minus" sample:

- Δl = (l⁻ − l⁺)·cos( (b⁻ + b⁺)/2 ) and Δb = b⁻ − b⁺;
- g_x = Δl·cos ψ + Δb·sin ψ;
- g_y = −Δl·sin ψ + Δb·cos ψ.

Then g = g_rx + g_tx and the angle is atan2(g_y, g_x) in degrees. The result is null if ψ is not finite or |g| < 1e-12.

### 5.5 Libration width factor W (`calcLibrationWidthFactor2D`, l.1640–1658)

This is called after BWF and BWF_ref have been normalised by A_moon.

- If all four offsets are exactly 0: W = sqrt(max(BWF, 0)). The comment calls this "the measured legacy law".
- Otherwise, with C = cov(current moments), C_ref = cov(reference moments), v = DirVar(C, angle) and v0 = DirVar(C_ref, angle):
  W = min( 1, sqrt(BWF_ref)·sqrt(v/v0) ).
- The code falls back to sqrt(BWF) if anything is invalid.
- W enters:
  - S/N_EME (−10·lg W);
  - the CW integration (t_int = B/2.5/W; x_σ ∝ sqrt(1/W));
  - S_mut,corr.

### 5.6 Q65 "SNR50 V2.3" research threshold (l.1662–1790; applied in `emeQ65V23Apply`, l.2746)

This model is attributed to Gerald Ihninger OE2IGL. It is displayed only and does not feed the margin.

**B4σ width** (`emeQ65V23B4sigma`):

B4σ = 2·S_full·sqrt(v)/a_moon [Hz]

- S_full = S_mut (`txrxlibspread`, Hz);
- v = DirVar( cov(emeLibMoments), gradient angle ) [deg²];
- a_moon = Moon radius [deg].
- Special values: B4σ = 0 if S_full = 0, and NaN if the inputs are invalid.
- For a uniformly weighted disc, v = a²/4, so B4σ = S_full. B4σ equals 4·σ_f of the echo Doppler distribution.

**Threshold:**

- x = ln(1 + B4σ/100);
- r = 1 if `reflectMode == "r"` (profile "moon_radial"), else 0 ("moon_uniform");
- thr = a + (b0 + r·db)·x + (c0 + r·dc)·x² [dB in 2500 Hz].

Coefficients (exactly as in the code):

| mode | a | b0 | c0 | db | dc | uniformMax | radialMax |
|---|---|---|---|---|---|---|---|
| 60D | −27.799065510158815 | 6.342473098004985 | 1.034934239946647 | −1.1569431866424726 | −0.4515028374598804 | 398.8381530798245 | 271.96039597973123 |
| 60E | −27.217151173627048 | 4.368477995719305 | 0.8979333773636435 | −0.9441650764550974 | 0.027863866608062733 | 398.8381530798245 | 271.96039597973123 |
| 120E | −29.918416892580833 | 9.429391203391209 | −0.4476032760558973 | −2.7029582996599135 | 1.1298794085287616 | 398.8381530798245 | 271.96039597973123 |

**Status logic** (first matching rule wins):

1. Uniform profile, mode 60D or 120E, and B4σ ≥ 1000 → `MODEL_ONLY_NO_P50_OBSERVED_AT_EXTREME_UNIFORM`.
2. B4σ > 1500 or S_full > 1500 → `OUTSIDE_0_TO_1500_DESIGN_DOMAIN_MODEL_ONLY`.
3. B4σ > uniformMax/radialMax (+1e-8) → `EXTRAPOLATED_THEORETICAL_0_TO_1500`.
4. Not the strict reference geometry → `TX_RX_GEOMETRY_ANALOGY`.
5. Otherwise → `V21_CONDITIONAL_FIT_REFERENCE_GEOMETRY`.

Strict reference geometry (`emeQ65V23StrictGeometry`), all conditions within the given tolerance:

- f = 10.368 GHz (±0.002);
- D_tx = D_rx = 0.6 m (±0.005);
- both shapes `g`;
- θ_tx = θ_rx = 3.3734° (±0.12);
- a_moon = 0.25° (±0.015);
- all offsets 0 (±0.002°).

Other statuses: `UNSUPPORTED_MODE`, `MISSING_DOPPLER_MOMENTS`, `NUMERIC_FAILURE`, `INVALID_INPUT`.

If the gradient angle is not finite, a warning is appended: "isotropic covariance average used".

Display (`emeQ65V23DisplayThreshold`): field `thresholdcorr` = thr with 2 decimals plus " dB", in grey, with the status in the tooltip.

The code comments say the fits are "conditional empirical fits for original −d3 known calls, no averaging". Larger B4σ values are extrapolations and not measured P50.

---

## 6. Lunar thermal emission

### 6.1 Data tables `lat0.js … lat80.js` (structure only)

`lat0.js` also defines:

- `phases`: 72 values, 0, 0.0139, 0.0278, … 0.9861, i.e. step 1/72. This is the lunar local-time fraction p ∈ [0, 1).
  - From the data: the surface maximum is at index 18 (p = 0.25), so p = 0.25 is local noon.
  - The minimum is at index 0 (p = 0, i.e. sunrise) for low latitudes.
  - So p = 0 is sunrise, 0.25 noon, 0.5 sunset, 0.75 midnight. This is inferred from the data and from phase1 = phase/360 + 0.25 (full Moon gives a disc centre at noon).
- `depths`: 500 values, 0.000 … 0.499, in steps of 0.001. Units are **metres**, inferred from the "to 30 m" comment and from κ in m⁻¹.

`t0, t10, …, t80` are arrays [72 phases][500 depths] of regolith temperature in K for |selenographic latitude| = 0°, 10°, …, 80°. They come from Köppen's "simple model for the thermal behaviour of lunar soil".

| table | surface T range [K] (min…max over phase) | deep value |
|---|---|---|
| t0 | 106.55 … 387.88 | 220.0 |
| t10 | 106.46 … 386.38 | 220.0 |
| t20 | 106.14 … 381.84 | 220.0 |
| t30 | 105.60 … 374.05 | 220.0 |
| t40 | 104.78 … 362.65 | 220.0 |
| t50 | 103.72 … 346.92 (overall min 103.61) | 220.0 |
| t60 | 97.61 … 325.55 | 220.0 |
| t70 | 94.61 … 295.64 | 220.0 |
| t80 | 92.32 … 248.67 | 220.0 |

All maxima are at phase index 18. The deepest layer (index 499) is 220.0 K for every phase.

### 6.2 `getTemp(p, lat_abs, id)` (l.3337–3382)

This is a bilinear interpolation in phase and latitude, at depth index `id`.

- Phase: i_p = ⌊p·72⌋ and i_p1 = i_p + 1. If i_p = 71, both are decremented (70, 71), so for p > 70/72 the value is **extrapolated** from the last bin. There is no wrap-around.
- Phase weight: w_p = (p − phases[i_p])/(phases[i_p1] − phases[i_p]).
- Latitude: in each 10° band [10k, 10k+10), w_t = (lat − 10k)/10 and the code interpolates linearly between t_{10k} and t_{10k+10}.
- For lat ≥ 80 only t80 is used, with no latitude interpolation.
- T = (t_a[i_p][id]·(1 − w_t) + t_b[i_p][id]·w_t)·(1 − w_p) + (t_a[i_p1][id]·(1 − w_t) + t_b[i_p1][id]·w_t)·w_p.

### 6.3 `getTemperature(p, l, d)` (l.3324–3334)

Linear interpolation in depth d [m] between the table depths:

- d ≤ 0 → id = 0;
- d ≥ 0.499 → id = 499;
- the function returns 0 if nothing matches.

### 6.4 `getRadioFlux(p, lat)` — microwave brightness temperature (l.3291–3321)

Absorption coefficient: κ = 2π·sqrt(ε_r)·tanδ·f/0.3 [m⁻¹], with ε_r = 1.5, tanδ = 0.0143 and f in GHz. At 10.368 GHz κ ≈ 3.80 m⁻¹.

With lat_abs = |lat|, Δz0 = depths[1] − depths[0] = 0.001 m, Δx = (3/κ)/50, and x_i = i·Δx for i = 1 … 125 (= depths.length/4):

T_B = T(p, lat, z = 0)·κ·Δz0 + Σ_{i=1}^{125} T(p, lat, x_i)·exp(−κ·x_i)·κ·Δx

If x_125 < 3 m, deeper layers are added up to about 30 m, using the deepest-table temperature T_deep = getTemp(p, lat, 499):

- Δx_b = (30 − x_125)/49;
- x_k = x_125 + k·Δx_b for k = 1 … 50;
- T_B += Σ_k T_deep·exp(−κ·x_k)·κ·Δx_b.

Notes:

- The integration ends at 30 + Δx_b, not exactly 30.
- There is no Fresnel emissivity and no refraction or viewing-angle path. Viewing geometry enters only via the rim correction (§6.5).
- The integral of κe^{−κx} is not exactly normalised to 1. The code reproduces Köppen's Java grid ("use same grid as in java").

### 6.5 `rimCorrection(r)` (l.3560–3567)

ρ = r/a_moon (normalised radius). The comment reads "eps=1.5 into eps=1".

C_rim(ρ) = (1 − ρ²)^( (0.0521/2)·(f/10)^0.210 ) (marked "OE2IGL 2025")

Earlier versions are commented out: 1 − ρ^32; 1 − 0.10·(1 − cos(asin ρ)); (1 − ρ²)^0.05.

### 6.6 `calcMoonTemp()` — disc map, average, centre and beam-weighted temperature (l.3385–3557)

Grid: x, y from −0.3 to +0.3 with N = `nxs` = `nys` points (the value set by `computeIntegrals`: 125, 80 or 50), so dx = 0.6/(N − 1). Note that this grid is slightly different from the one in §2.1.

Rotation into the Sun-aligned frame:

- tilt = δ_sun + π (§9.6);
- x = xx·cos(tilt) + yy·sin(tilt) and y = yy·cos(tilt) − xx·sin(tilt).

On the disc (x² + y² ≤ a_moon²):

- "latitude" lat = asin(y/a_moon) and "longitude" lon = asin( x/(a_moon·cos lat) );
- **Code:** these are coordinates relative to the Sun direction projected on the sky. The subsolar point is assumed to lie on this "equator". The real selenographic coordinates and libration are not used. **UNCLEAR** if intended.
- Local time: p = phase1 + lon/(2π), folded into [0, 1), with phase1 = phase/360 + 0.25 (§9.6).
- Brightness: T_B(x, y) = 1.07·getRadioFlux(p, lat_deg)·C_rim( sqrt(x² + y²)/a_moon ).
  - The factor 1.07 is unexplained (**UNCLEAR**: calibration or emissivity factor).

Off the disc, T_B = 0.

Results:

- T_avg = mean of T_B over the on-disc grid points (unweighted count). Field `tavg`.
- T_cen = 1.07·getRadioFlux(phase1, 0) (centre, no rim term). Field `tcen`.
- **Beam-weighted antenna temperature** (the return value):

  T_moon,beam = Σ T_B·exp( −((x − x_rx)² + (y − y_rx)²)/(2σ²) )·dx·dy / (2πσ²), with σ = θ_rx/2.3548.

  - A Gaussian RX beam is always assumed, whatever the RX shape.
  - The normalisation is the full Gaussian solid angle, so the Moon fill factor is implicit: T_moon,beam ≈ F_moon·⟨T_B⟩_beam.
  - **Code:** the RX offset is applied in the rotated (Sun-aligned) coordinates, not in the sky frame used by `computeIntegrals` (§13).
  - In `compute`: T_moon = T_moon,beam·τ_rx.
- Image mode `beamtempmap` (and `timer == 0`): the map is smoothed with the same Gaussian, including zero-padding contributions to the normaliser from a 5× larger frame when θ_rx > 0.1. The brightest smoothed pixel (xpeak, ypeak, hpeak) is shown as "max moon noise". Visualisation only.

Frequency dependence of the Moon temperature enters through κ (penetration depth), the rim exponent and the radial reflectance. There is no separate emissivity spectrum. Lunar phase enters through phase1 and p. Position on the disc enters through (lat, lon) in the Sun-aligned frame and through C_rim.

### 6.7 Old model `getMoonTemp()` (l.3262–3288, "not used anymore")

This model combines Foster 1969, Köppen and Morgan 2018. Let λ_cm = 30/f (f in GHz) and N_d = `mooncycle` (days after full Moon).

- f < 10 GHz:
  - a = 252·λ_cm^(−2.291);
  - b = (π/5)·λ_cm^0.275·180/π [deg];
  - c = 244.56·λ_cm^(−0.036457).
- f ≥ 10 GHz:
  - a = 16.336λ⁴ − 114.17λ³ + 281.66λ² − 303.27λ + 152.1;
  - b = (π/5)·λ^0.275·180/π;
  - c = 10.256λ⁴ − 59.061λ³ + 111.94λ² − 84.104λ + 250.8.
- T = c + a·cos( (360/28)·N_d − b ) (argument in degrees).

Commented-out alternatives in the code:

- a = 28.4λ^(−0.908) (Morabito);
- a = 30λ^(−0.67) and c = 213 (Foster);
- b = 43.83/(1 + 0.0109f) and c = 207.7 + 24.43/f (Morgan);
- a = c·0.004212·f^1.224 (Morgan).
---

## 7. Atmosphere

### 7.1 Model used: `attenuation2(T, RH, P)` — ITU-R P.676-13 (08/2022), Annex 1 line-by-line + Annex 2 equivalent heights (l.3572–3629)

Inputs:

- T: air temperature [°C], input range −30…40, default 15;
- RH: relative humidity [%], 0…100, default 50;
- P: absolute (station) pressure [hPa], 800…1050, default 980;
- the global f [GHz].

Output: zenith attenuation [dB]. It is called separately for TX and RX with each station's weather.

**Humidity** (Magnus form):

- θ = 300/(T + 273.15);
- ρ = 6.112·RH·2.1674·exp(17.67·T/(243.5 + T))/(T + 273.15) [g/m³], i.e. ρ = 216.74·(RH/100)·e_s/T_K;
- e = ρ·(T + 273.15)/216.7 [hPa];
- p = P − e (dry pressure).

**Dry continuum:**

- d = 5.6e-4·(p + e)·θ^0.8;
- N″_D = f·p·θ²·[ 6.14e-5/( d·(1 + (f/d)²) ) + 1.4e-12·p·θ^1.5/(1 + 1.9e-5·f^1.5) ].

**Oxygen lines.** `oxyatt` has 44 lines of 7 columns: f0, a1, a2, a3, a4, a5, a6. This is P.676-13 Table 1; the table runs from 50.474214 to 834.145546 GHz and the a4 column is 0 everywhere. For each line:

- S = a1·1e-7·p·θ³·exp(a2·(1 − θ));
- Δf = a3·1e-4·( p·θ^(0.8 − a4) + 1.1·e·θ ), then Δf ← sqrt(Δf² + 2.25e-6);
- δ = (a5 + a6·θ)·1e-4·(p + e)·θ^0.8;
- F = (f/f0)·[ (Δf − δ(f0 − f))/((f0 − f)² + Δf²) + (Δf − δ(f0 + f))/((f0 + f)² + Δf²) ];
- N″_ox = Σ S·F.

**Water-vapour lines.** `vapatt` has 35 lines: f0, b1 … b6. This is P.676-13 Table 2, from 22.235080 to 1780.000000 GHz. For each line:

- S = b1·1e-1·e·θ^3.5·exp(b2·(1 − θ));
- Δf = b3·1e-4·( p·θ^b4 + b5·e·θ^b6 );
- Δf ← 0.535·Δf + sqrt(0.217·Δf² + 2.1316e-12·f0²/θ);
- δ = 0;
- the same line shape F as for oxygen;
- N″_w = Σ S·F.

**Specific attenuations** [dB/km]: γ_o = 0.1820·f·(N″_ox + N″_D) and γ_w = 0.1820·f·N″_w.

**Equivalent heights** [km]:

- Oxygen: `slantoxy` has 700 rows of [f, a0, b0, c0, d0] for f = 1.0 … 350.0 GHz in steps of 0.5 GHz (Annex 2 coefficient table).
  - The code finds the first row with f_row ≥ f and steps back one row. It then interpolates every coefficient linearly with slope (c_{i+1} − c_i)/0.5.
  - h_o = a0 + b0·T_K + c0·P + d0·ρ, with T_K = T + 273.15, P total pressure in hPa and ρ in g/m³.
  - f = 1.0 exactly would index row −1, but the input requires f > 1.
- Water vapour: h_w = A·f + B + Σ_{i=1}^{3} a_i/((f − f_i)² + b_i), with A = 5.6585e-5 and B = 1.8348. `slantvap` provides [f_i, a_i, b_i] = [22.235080, 2.6846, 2.7649], [183.310087, 5.8905, 4.9219], [325.152888, 2.9810, 3.0748].

**Zenith attenuation:** A_zen = γ_o·h_o + γ_w·h_w [dB].

**Use in the link budget:**

- A_zen,tot = A_zen + cloud loss (input dB: TX 0…50, RX 0…20, default 0);
- slant attenuation A(E) = A_zen,tot/sin E;
- sky temperature from attenuation: T_sky = T_m·(1 − 10^(−A/10)) with T_m = 0.81·T_K + 37.4 (§4.4).

### 7.2 Old model `attenuation(T, RH, P)` — ITU-R P.676-10 (09/2013), Annex 2 approximate (l.3632–3714). Not called anywhere.

**Inputs and helper functions:**

- rp = P/1013, rt = 288/(273 + T);
- ρ_sat = 5.018 + T·(0.32321 + T·(8.1847e-3 + T·3.1243e-4)) and ρ = RH·ρ_sat/100;
- φ(rp, rt, a, b, c, d) = rp^a·rt^b·exp( c(1 − rp) + d(1 − rt) );
- g(f, fi) = 1 + ((f − fi)/(f + fi))²;
- gw(η, a, rt, f, f0, b) = η·exp(a(1 − rt))/((f − f0)² + b·η²).

**Dry air γ0 [dB/km]:**

- f ≤ 54:
  - ξ1 = φ(0.0717, −1.8132, 0.0156, −1.6515), ξ2 = φ(0.5146, −4.6368, −0.1921, −5.7416), ξ3 = φ(0.3414, −6.5851, 0.2130, −8.5854);
  - γ0 = [ 7.2·rt^2.8/(f² + 0.34·rp²·rt^1.6) + 0.62·ξ3/((54 − f)^(1.16ξ1) + 0.83ξ2) ]·f²·1e-3.
  - **Code:** there is no rp² factor here, unlike the other bands.
- 54 < f ≤ 60:
  - γ54 = 2.192·φ(1.8286, −1.9487, 0.4051, −2.8509), γ58 = 12.59·φ(1.0045, 3.5610, 0.1588, 1.2834), γ60 = 15.0·φ(0.9003, 4.1335, 0.0427, 1.6088);
  - γ0 = exp[ ln γ54/24·(f − 58)(f − 60) + ln γ58/8·(f − 54)(f − 60) + ln γ60/12·(f − 54)(f − 58) ].
  - **Code:** the γ58 term has a + sign; see §13.
- 60 < f ≤ 62: γ62 = 14.28·φ(0.9886, 3.4176, 0.1827, 1.3429); γ0 = γ60 + (γ62 − γ60)(f − 60)/2.
- 62 < f ≤ 66:
  - γ64 = 6.819·φ(1.4320, 0.6258, 0.3177, −0.5914), γ66 = 1.908·φ(2.0717, −4.1404, 0.4910, −4.8718);
  - γ0 = exp[ ln γ62/8·(f − 64)(f − 66) + ln γ64/4·(f − 62)(f − 66) + ln γ66/8·(f − 62)(f − 64) ].
- 66 < f ≤ 120:
  - ξ4 = φ(−0.0112, 0.0092, −0.1033, −0.0009), ξ5 = φ(0.2705, −2.7192, −0.3016, −4.1033), ξ6 = φ(0.2445, −5.9191, 0.0422, −8.0719), ξ7 = φ(−0.1833, 6.5589, −0.2402, 6.131);
  - γ0 = [ 3.02e-4·rt^3.5 + 0.283·rt^3.8/((f − 118.75)² + 2.91·rp²·rt^1.6) + 0.502·ξ6·(1 − 0.0163·ξ7·(f − 66))/((f − 66)^(1.4346ξ4) + 1.15ξ5) ]·f²·rp²·1e-3.
- 120 < f ≤ 350:
  - δ = −0.00306·φ(3.211, −14.94, 1.583, −16.37);
  - γ0 = [ 3.02e-4/(1 + 1.9e-5·f^1.5) + 0.283·rt^0.3/((f − 118.75)² + 2.91·rp²·rt^1.6) ]·f²·rp²·1e-3 + δ.
- f > 350: returns undefined.

**Water vapour:**

- η1 = 0.955·rp·rt^0.68 + 0.006ρ and η2 = 0.735·rp·rt^0.5 + 0.0353·rt⁴·ρ;
- γw = [ 3.98·gw(η1, 2.23, 22.235, 9.42)·g(f, 22) + 11.96·gw(η1, 0.7, 183.31, 11.14) + 0.081·gw(η1, 6.44, 321.226, 6.29) + 3.66·gw(η1, 1.6, 325.153, 9.22) + 25.37·gw(η1, 1.09, 380, 0) + 17.4·gw(η1, 1.46, 448, 0) + 844.6·gw(η1, 0.17, 557, 0)·g(f, 557) + 290·gw(η1, 0.41, 752, 0)·g(f, 752) + 8.3328e4·gw(η2, 0.99, 1780, 0)·g(f, 1780) ]·f²·rt^2.5·ρ·1e-4.

**Heights:**

- t1 = 4.64/(1 + 0.066·rp^−2.3)·exp(−((f − 59.7)/(2.87 + 12.4·e^(−7.9rp)))²);
- t2 = 0.14·e^(2.12rp)/((f − 118.75)² + 0.031·e^(2.2rp));
- t3 = 0.0114/(1 + 0.14·rp^−2.6)·f·(−0.0247 + f(0.0001 + 1.61e-6·f))/(1 + f(−0.0169 + f(4.1e-5 + 3.2e-7·f)));
- h0 = 6.1·(1 + t1 + t2 + t3)/(1 + 0.17·rp^−1.1); if f < 70, h0 = min(h0, 10.7·rp^0.3);
- σw = 1.013/(1 + exp(−8.6(rp − 0.57)));
- hw = 1.66·(1 + 1.39σw/((f − 22.235)² + 2.56σw) + 3.37σw/((f − 183.31)² + 4.69σw) + 1.58σw/((f − 325.1)² + 2.89σw)).

**Result:** A_zen = γ0·h0 + γw·hw.

### 7.3 Clouds and rain

There is no cloud or rain model in the code. The user enters an "additional cloud loss [dB]", which is added to the zenith attenuation and therefore scaled by 1/sin E. It also raises the sky temperature.

The HTML gives guidance values (not used by the code):

- Specific cloud/fog loss [dB/km]:

  | Condition | 10 GHz | 47 GHz | 76 GHz |
  |---|---|---|---|
  | Cloud / less fog | 0.001 | 0.04 | 0.09 |
  | Medium fog (visibility 300 m) | – | 0.085 | 0.17 |
  | Thick fog (visibility 50 m) | – | 0.85 | 1.74 |

- Specific rain loss [dB/km]:

  | Rain rate | 10 GHz | 24 GHz | 47 GHz | 76 GHz |
  |---|---|---|---|---|
  | 0.1 mm/h (drizzle) | 0.0007 | 0.014 | 0.09 | 0.2 |
  | 1 mm/h (light rain) | 0.01 | 0.14 | 0.59 | 1.1 |
  | 10 mm/h (medium rain) | 0.21 | 1.4 | 3.9 | 5.8 |
  | 100 mm/h (tropical/thunderstorm) | 3.7 | 14.0 | 25.7 | 30.4 |

---

## 8. Refraction

### 8.1 `GetRefractionRadio(el, T, RH, P)` — used for the locked TX/RX elevations (l.3855–3904)

The comment claims ITU-R P.453 / P.834. el is the true elevation in degrees, clamped to ≥ 0.1.

1. e_s = 6.1121·exp(17.502·T/(T + 240.97)) [hPa] and e = (RH/100)·e_s.
2. T_K = T + 273.15 and N = 77.6·P/T_K + 3.75e5·e/T_K².
3. τ = (N·1e-6)/tan(el) [rad], converted to degrees.
4. If el < 15°:
   - x = sin(el)·sqrt(R_E/(2·H)), with R_E = 6371 km and H = 8.0 km;
   - erf_x = 1 − 1/(1 + 0.278393x + 0.230389x² + 0.000972x³ + 0.078108x⁴)⁴ (the Abramowitz–Stegun erf approximation);
   - τ ← τ·erf_x.
5. The function returns τ [deg], which is added to the true elevation.

**Note:** the HTML says the radio refraction is "based on A.L. Berman", but the active function is the one above. Berman's model is `GetRefractionRadio1`, which is unused (§13).

### 8.2 `GetRefractionRadio1(el, T, RH, P)` — Berman & Rockwell (1976) radio model (l.3907–3931). Not called.

Constants:

- p0 = 760, A1 = 0.40816, A2 = 112.3, t0 = 273, B1 = 0.12820, B2 = 142.88;
- C0 = 91.87, C1 = 0.8, C2 = 99.344;
- W0 = 22000, W1 = 17.149, W2 = 4684.1, W3 = 38.45;
- K[0..11] as listed in §0.

With χ = 90 − el:

- p_z = (P/1013·p0 − p0)·exp(A1·(χ − A2));
- t_z = T·exp(B1·(χ − B2));
- z = (χ − C0)·exp(C1·(χ − C2));
- u = (χ − K0)/K1;
- F_p = (P/1013)·(1 − p_z/(1 + z));
- F_t = ((T + t0)/t0)·(1 − t_z/(1 + z));
- F_w = 1 + W0·(RH/100)/(T + t0)/(P/1013·p0)·exp( (W1·(T + t0) − W2)/(T + t0 − W3) );
- F_a = exp( (Σ_{i=0}^{8} K_{i+2}·u^i)/(1 + z) );
- R = F_p·F_t·F_w·(F_a − K11)/3600 [deg].

### 8.3 `GetRefractionRadio2` — Yebes IT-OAN-2003-2 (l.3934–3940). Not called.

- p_w = 6.105·(RH/100)·Math.pow((273 + T)/273 − 5.31)·exp(25.22·T/(273 + T)).
  - **BUG?** `Math.pow` is called with a single argument, so the result is NaN. ((273 + T)/273)^(−5.31) was probably intended.
- refcorr = 16.01/(273 + T)·(P − 0.072·p_w + 4831·p_w/(273 + T));
- R = refcorr·|tan(90 − el − 5.9/(el + 2.5))|/3600 [deg].

### 8.4 `GetRefraction(el)` — optical (Meeus 1991, Sæmundsson-type) (l.3943–3947)

- s = 1.02/tan(el + 10.3/(5.11 + el)) (argument in degrees);
- R = REFCON·( s − 0.12·sin(14.8·s + 8.0) ) [deg], with REFCON = 0.015.

It is used only for the displayed Sun/Moon elevations `els`/`elm` ("only optical refractive elevation corr.").

---

## 9. Astronomy

### 9.1 Time

- `getDoy()` (l.3785): day of year from the 0-based month, with the Gregorian leap rule.
- `Tosec()` (l.3805): t1970 = seconds since 1970-01-01 00:00 UTC (UT, no leap seconds, no ΔT).
- `Tosec2(y, d, h, m, s)` does the same for a given date. t2000 = Tosec2(2000, 1, 12, 0, 0) is J2000.0 = 2000-01-01 12:00.
- Ephemeris time: t = t1970 + ΔT, with ΔT = 70 s, and T = (t − t2000)/86400/36525 (Julian centuries).
- `compute1()` re-derives everything on every call.

### 9.2 `getGST()` (l.3830–3838)

- x = t1970 − 915210980.1948 s (UT; an epoch at which GST = 0 is implied);
- P_sid = 86164.09053 s;
- x ← x − P_sid·round(x/P_sid);
- GST = 2π·x/P_sid [rad]. Because of the rounding, the range is (−π, π].

### 9.3 `SunRaDec()` (l.3974–4006) — Meeus low-precision Sun (ch. 25 style)

- M = 357.52911 + 35999.05029·T − 0.0001537·T² + T³/24490000 [deg].
- True geometric longitude:
  λ☉ = 280.46646 + 36000.76983·T + 0.0003032·T² + (1.914602 − 0.004817·T − 0.000014·T²)·sin M + (0.019993 − 0.000101·T)·sin 2M + 0.000289·sin 3M [deg].
  There is no aberration or nutation. The value is folded to [0, 2π) and stored as `elongs`.
- Obliquity (IAU 1984): ε = 23.43929111 + T·(−46.8150 + T·(−0.00059 + 0.001813·T))/3600.
- δ = asin(sin λ☉·sin ε) and α = atan2(sin λ☉·cos ε, cos λ☉) in [0, 2π). Geocentric, no parallax.
- The code states no accuracy. From outside knowledge: Meeus ch. 25 quotes about 0.01° for this low-precision method.

### 9.4 `MoonRaDec()` (l.4009–4129) — Montenbruck & Pfleger "MiniMoon" + Meeus distance series + topocentric correction

All angles are in revolutions converted to radians.

- M☉ = 0.993133 + 99.997361·T.
- L0 = frac(0.606433 + 1336.855225·T).
- M′ (Mm) = 0.374897 + 1325.552410·T.
- D = 0.827361 + 1236.853086·T.
- F = 0.259086 + 1342.227825·T.
- E = 1 − T·(0.002516 + 0.0000074·T).

Longitude perturbation dL [arcsec]:

dL = 22640 sin M′ − 4586 sin(M′ − 2D) + 2370 sin 2D + 769 sin 2M′ − 668 sin M☉ − 412 sin 2F − 212 sin(2M′ − 2D) − 206 sin(M′ + M☉ − 2D) + 192 sin(M′ + 2D) − 165 sin(M☉ − 2D) − 125 sin D − 110 sin(M′ + M☉) + 148 sin(M′ − M☉) − 56 sin(2F − 2D)

Latitude:

- S = F + (dL + 412·sin 2F + 514·sin M☉)·ARCS;
- N = −526 sin(F − 2D) + 44 sin(M′ + F − 2D) − 31 sin(−M′ + F − 2D) − 23 sin(M☉ + F − 2D) − 11 sin(−M☉ + F − 2D) − 25 sin(−2M′ + F) + 21 sin(−M′ + F);
- λ☾ = 2π·(L0 + dL/1296000), folded (`elongm`);
- β☾ = (18520·sin S + N)·ARCS.

Ecliptic → equatorial rotation by ε (as in §9.3), giving the unit vector (xx, yy, zz).

Geocentric distance R [km]: R = 385000.56 + ΣR/1000. ΣR is the full Meeus Table 47.A distance series, in units of 0.001 km, evaluated with the MiniMoon arguments M′, D, F, M☉ and E. The coefficients are (cos terms):

| Coefficient | Argument | Coefficient | Argument | Coefficient | Argument |
|---|---|---|---|---|---|
| −20905355 | M′ | −3699111 | 2D − M′ | −2955968 | 2D |
| −569925 | 2M′ | +48888·E | M☉ | −3149 | 2F |
| +246158 | 2D − 2M′ | −152138·E | 2D − M☉ − M′ | −170733 | 2D + M′ |
| −204586·E | 2D − M☉ | −129620·E | M☉ − M′ | +108743 | D |
| +104755·E | M☉ + M′ | +10321 | 2D − 2F | +79661 | M′ − 2F |
| −34782 | 4D − M′ | −23210 | 3M′ | −21636 | 4D − 2M′ |
| +24208·E | 2D + M☉ − M′ | +30824·E | 2D + M☉ | −8379 | D − M′ |
| −16675·E | D + M☉ | −12831·E | 2D − M☉ + M′ | −10445 | 2D + 2M′ |
| −11650 | 4D | +14403 | 2D − 3M′ | −7003·E | M☉ − 2M′ |
| +10056·E | 2D − M☉ − 2M′ | +6322 | D + M′ | −9884·E² | 2D − 2M☉ |
| +5751·E | M☉ + 2M′ | −4950·E² | 2D − 2M☉ − M′ | +4130 | 2D − 2F + M′ |
| −3958·E | 4D − M☉ − M′ | +3258 | 3D − M′ | +2616·E | 2D + M☉ + M′ |
| −1897·E | 4D − M☉ − 2M′ | −2117·E² | 2M☉ − M′ | +2354·E² | 2D + 2M☉ − M′ |
| −1423 | 4D + M′ | −1117 | 4M′ | −1571·E | 4D − M☉ |
| −1739 | D − 2M′ | −4421 | 2M′ − 2F | +1165·E² | 2M☉ + M′ |
| +8752 | 2D − 2F − M′ | | | | |

Derived quantities:

- Geocentric angular diameter: diam = atan(2·R_moon/R) [deg] (display `diam`). a_moon = diam/2 is the radius used in **all** disc integrals.
- Topocentric position, for each station (lat φ, lon λ):
  - aam = R/REARTH, ha = GST + λ;
  - x = xx − cos φ·cos(ha)/aam, y = yy − cos φ·sin(ha)/aam, z = zz − sin φ/aam (spherical Earth, geodetic latitude used as geocentric);
  - R_topo = |(x, y, z)|·R − R_moon. This is the topocentric distance to the **near surface** of the Moon.
  - If the `#station` select equals this station, ra = atan2(y, x) and dec = atan2(z, sqrt(x² + y²)) are set. The topocentric diameter atan(2R_moon/(R_topo + R_moon)) and R_topo are shown (display only).
- **dmoon** = (R_topo,rx + R_topo,tx)/2, used in the path loss.
- No nutation is applied. The code states no accuracy. From outside knowledge, not from the code: Montenbruck & Pfleger give MiniMoon an accuracy of a few arcminutes.

### 9.5 `MoonDistance()` (l.4147–4195) and `MoonRadialVelocity()` (l.4138–4144)

`MoonDistance()` uses the Meeus 1991 arguments [deg]:

- D = 297.8502042 + T(445267.1115168 + T(−0.0016300 + T(1/545868 − T/113065000)));
- M☉ = 357.5291092 + T(35999.0502909 + T(−0.0001536 + T/24490000));
- M′ = 134.9634114 + T(477198.8676313 + T(0.0089970 + T(1/69699 − T/14712000)));
- F = 93.2720993 + T(483202.0175273 + T(−0.0034029 + T(−1/3526000 + T/863310000)));
- E as above.

R = 385000.56 + ΣR/1000 km, with the same table as §9.4. `rangeA` folds angles into 0…360.

`MoonRadialVelocity()` = (R(t + 60 s) − R(t))/60 [km/s].

Both functions are **not used**. The code computes no Doppler shift from range rate.

### 9.6 `Radec2Azel()` (l.3950–3971) and `compute1()` derived angles (l.3070–3197)

**Radec2Azel:**

- LST = GST + long (east positive) and H = LST − α;
- p = sin δ, w = sin H·cos δ, r = cos H·cos δ;
- zen = r·cos φ + p·sin φ and north = −r·sin φ + p·cos φ;
- el = atan2(zen, sqrt(north² + w²)) and az = fold(atan2(−w, north)) [deg], with azimuth measured from north through east.

**compute1 order:**

1. Sun RA/Dec, then Az/El. El_true is stored as `elsunsim`/`azsunsim`; the displayed El includes the optical refraction.
2. a_sun = SunDiameter()/2.
3. Moon RA/Dec (topocentric for the `#station` site), then Az/El. El_true is `elmoonsim`; `azm` is the azimuth.

**Phase:** phase = fold(λ☾ − λ☉ + π) in degrees, with 0 = full Moon. The phase names are assigned in 15/75/105/165/195/255/285/345° steps:

| phase [deg] | name |
|---|---|
| < 15 | full moon |
| < 75 | waning gibbous |
| < 105 | last quarter |
| < 165 | waning crescent |
| < 195 | new moon |
| < 255 | waxing crescent |
| < 285 | first quarter |
| < 345 | waxing gibbous |
| ≥ 345 | full moon |

**Moon-cycle quantities:**

- phase1 = phase/360 + 0.25 (mod 1) is the local-time fraction at the disc centre;
- mooncycle = phase/360·28 (days after full Moon, with a 28-day cycle).

**Direction to the Sun on the disc.** This uses the true (airless) elevations e_m, e_s and azimuths A_m, A_s:

- cos c = sin e_m·sin e_s + cos e_m·cos e_s·cos(A_s − A_m), and the Sun–Moon distance is c;
- sin δ′ = sin(A_s − A_m)/sqrt(1 − cos²c)·cos e_s;
- cos δ′ = (sin e_s − cos c·sin e_m)/(sqrt(1 − cos²c)·cos e_m);
- δ = π/2 − atan2(sin δ′, cos δ′) (`deltam`, used to draw the Sun-direction line).
- Display "angle to Sun": 450 − δ° if phase ≤ 180; otherwise 90 − δ°, and δ ← δ + π.
- tilt = δ + π, used by `calcMoonTemp`.
- The Sun–Moon angular distance is flagged red if it is < 10°.

**Solar-eclipse flag:** (Δα² + Δδ²) [deg²] < (a_moon + a_sun)². No cos δ factor is applied to Δα.

**SunDiameter()** (l.4132): d☉ = (31.995 + 0.535·cos(2π·doy/365.24))/60 [deg]. The commented-out old version is 31.905 + 0.54 cos(…).

### 9.7 `locator2latlon(loc)` (l.2909–2951)

Short locators are padded to 10 characters with "55LL55LL", "LL55LL", "55LL" or "LL". The result must match `[A-R]{2}[0-9]{2}[A-X]{2}[0-9]{2}[A-X]{2}`, otherwise the function returns (0, 0).

- lat = 10·(c2 − 'A') + (c4 − '0') + (c6 − 'A')/24 + (c8 − '0')/240 + (c10 − 'A')/5760 − 90
- lon = 20·(c1 − 'A') + 2·(c3 − '0') + (c5 − 'A')/12 + (c7 − '0')/120 + (c9 − 'A')/2880 − 180

The result is the south-west corner of the padded 10-character square. For a 6-character locator this lies 11/5760° north and 11/2880° east of the 6-character centre, i.e. not exactly the centre.

---

## 10. Feed and dish models (`compute`, l.1981–2347; mesh in `readFields`)

All of these are **display quantities** ("max. antenna efficiency", "max gain"). They do not enter the link budget, except:

- bf, which sets the HPBW and η_MB;
- center-to-rim and feed tilt, which enter the spillover model;
- η_s,sim, which sets η_F for shape `x`.

### 10.1 Dish geometry

Focal length F = (f/D)·D. Inputs: f/D 0…2; offset angle φ_off (TX 0…30°, RX 0…50°).

- xh = 2F·sqrt( (1/cos φ_off)² − 1 ) = 2F·tan φ_off;
- a = (D/2 + xh)²/(4F) + F and b = (D/2 − xh)²/(4F) + F (focal distances to the two rim points);
- half opening angle "dish centre – rim":
  θ0 = (1/2)·arccos( (a² + b² − (D/cos φ_off)²)/(2ab) ) [deg];
- RX feed tilt ψ_t = θ0 for an offset dish, 0 for prime focus (§4.5).

### 10.2 Feed taper from edge taper (display)

- Prime focus (φ_off = 0): T_feed = T_e + 20·lg(1 + (1/(4·f/D))²). This is the space-attenuation term.
- Offset (an empirical construction, written exactly as coded):
  - h1 = 2F·sqrt(cos⁻²φ_off − 1) − D/2;
  - ψS = atan( 8FD/(16F² + 4(D/2 + h1)² − D²) );
  - ψB = atan( 16F(D/2 + h1)/(16F² − 4(D/2 + h1)² + D²) ) [deg];
  - ψL = ψB − ψS and ψU = 2ψS + ψL;
  - Q = 40·lg( cos(ψL/2)/cos(ψU/2) );
  - ψP = Q·ψS·2/4.014/(−2T_e − Q) + ψS and ψF = ψP + ψL;
  - tapL = −40·lg cos(ψL/2), tapU = −40·lg cos(ψU/2), tap1 = −40·lg cos(ψF/2), tap2 = (tapL + tapU)/2;
  - T_feed = T_e + tap2 − tap1.

### 10.3 Gaussian-illumination parameters (shapes `g` and `x`)

ρ = −T_e/20·2.303 (T_e in dB, negative). Note the /20.

- η_i = 2(1 − e^(−ρ))²/(ρ(1 − e^(−2ρ))) (display "Illumination efficiency");
- η_s = 1 − e^(−2ρ) (spillover);
- η_i·η_s = 2(1 − e^(−ρ))²/ρ, which is 0.8122 at T_e = −10 dB (the HTML quotes "81.5%");
- shape `g` assumes η_phase = 1.0 and η_pol = 0.985;
- a yellow warning appears if η_real > 2(1 − e^(−ρ))²/ρ.
- For shape `e`: ρ = 0.1/20·2.303 (used only inside the focus formula). Illumination, spillover and their product are 1.00, and η_pol = 0.985.
- For shape `x`: η_i, η_s, η_phase and η_pol are the "sim" inputs. A warning appears if η_real > η_i,sim·η_s,sim.

### 10.4 Surface efficiency: Ruze + "2-string" astigmatism (l.2032–2033)

η_sur = exp( −(4π·ε_rms/λ)² ) · exp( −[ (2π/√6)/λ · (1 − cos θ0) · 16·g_s·(f/D)²/2 ]² )

- ε_rms [m] = input rms [mm]/1000, range 0…50 mm;
- g_s [m] = "2-string method gap" [mm]/1000, range 0…50.
- The displayed "peak err" is ±2·ε_rms (rms·4/2).

### 10.5 Blockage

The input is the blocking **area** A_b [m²]; the code converts it to a diameter d_b = sqrt(4A_b/π). Ranges: TX 0…3 m, RX 0…2 m.

- `g`, `x`: η_b = [ (exp(−ρ(d_b/D)²) − e^(−ρ))/(1 − e^(−ρ)) ]².
- `e`: η_b = [ 1 − (1.061/1.029)²·(d_b/D)² ]², written in the code as 1 − 1/(1.029/1.061)²·(d_b/D)².

### 10.6 Focus efficiency: axial and lateral defocus (l.2036–2038)

Δz = axial defocus [mm] and Δx = lateral defocus [mm], both in 0…200.

Axial:

- u = (Δz/1000/λ)·(1 − cos(2·atan(1/(4·f/D))));
- η_ax = ρ²·(1 − 2e^(−ρ)·cos(2πu) + e^(−2ρ)) / ( (ρ² + 4π²u²)·(1 − e^(−ρ))² ).

Lateral, with t = tan(θ0/2):

- K = sin θ0 − [ 2(t² − ln(1 + t²))/t⁴ ]·2t;
- η_lat = exp( −[ (2π/(2√2))/λ · (Δx/1000) · K ]² ).

η_focus = η_ax·η_lat. The HTML notes that lateral defocus can be pointed out, but coma remains.

### 10.7 Mesh loss (T.Y. Otoshi; `readFields` l.1041, 1253)

- d = wire diameter [mm] + 0.001 and s = grid spacing [mm] + 0.001 (inputs 0…30 and 0…100 mm). The 0.001 offsets avoid division by zero.
- η_mesh = 1 − [ λ_mm/( 2s·ln(1/(1 − exp(−π d/s))) ) ]^(−2), with λ_mm = 1000·λ.
- η_mesh is clamped to ≥ 1e-9.
- The loss is shown in dB. With both inputs 0, η_mesh ≈ 1.

### 10.8 Max efficiency and gains (display)

- `g`: η_max = η_mesh·[2(1 − e^(−ρ))²/ρ]·η_sur·η_pol(0.985)·η_b·η_focus + (−0.025). The HTML calls this "theor. −2.5%". **Additive.**
- `e`: η_max = η_pol·η_b,e·η_sur·η_focus. Mesh is not included.
- `x`: η_max = η_mesh·η_i,sim·η_s,sim·η_sur·η_phase,sim·η_pol,sim·η_b·η_focus. There is no −0.025.

Gains:

- G_theo = (πD/λ)²;
- G_max = G_theo·η_max;
- "illum·spill gain" = G_theo·(η_i η_s), times η_phase·η_pol for `g`.

The fields `txmaxeff`/`rxmaxeff` turn yellow if η_max < 0. "Ohmic efficiency" fields exist in the HTML but are never read.

---

## 11. Other physics

### 11.1 Sun brightness temperature `solarTemp(x)` (l.3200–3229)

x is in MHz (f·1000). The comment says "from A.O.Benz (2003)", brightness temperature at disc centre. a_sun = solar radius in degrees and f in GHz.

| Range | Formula |
|---|---|
| 30 ≤ x < 350 | T = 3.19e5·x^0.1375 |
| 350 ≤ x < 6000 | T = 1.79e9·x^(−1.343) if SFU flux = 0; otherwise T = Flux/(9.63·tan²(a_sun)·f²) |
| otherwise (x ≥ 6000, also x < 30) | flux = 0: T = 10^(P7(lg x)) · tan²(0.53333°/2)/tan²(a_sun); flux > 0: T = Flux/(9.63·tan²(a_sun)·f²) |

The degree-7 polynomial is P7(L) = 0.0627788919882473·L⁷ − 1.80563289042362·L⁶ + 21.380411555905·L⁵ − 132.503464883081·L⁴ + 445.706342691881·L³ − 727.386111949714·L² + 272.782999151144·L + 420.57577950929.

- The SFU→K conversion divides by 9.63·tan²(a_sun)·f². This is consistent with T = S·1e-22·λ²/(2k·π·tan²a_sun) for f in GHz (my derivation; the code gives only the constant 9.63).
- The flux input range is 0…500000 SFU, default 0 (use the model).
- Commented-out alternatives:
  - 88311·x^(−0.214) (Benz);
  - "Trad" 2.888/tan²(a_sun)·x^(−0.25185);
  - "Tcenter" 2.344/tan²(a_sun)·x^(−0.233).

HTML reference table (32′ disc, centre temperature lower):

| Frequency [MHz] | T [K] | Flux [SFU] |
|---|---|---|
| 10368 | 12950 | 292 |
| 24048 | 10475 | 1270 |
| 47088 | 8840 | 4110 |
| 76032 | 7840 | 9500 |
| 122250 | 6960 | 21800 |
| 241920 | 5860 | 71800 |

### 11.2 Decoder thresholds

See §4.8 (legacy) and §5.6 (V2.3).

### 11.3 HTML reference dish data (informative)

| Parameter | DL0SHF 10 GHz | DL0SHF 24 GHz |
|---|---|---|
| Diameter | 7.2 m | 3.7 m |
| f/D | 0.35 | 0.35 |
| Surface rms | 0.85 mm | 0.35 mm |
| Feed blocking diameter | 0.3 m | 0.3 m |
| HPBW | 0.3° | 0.26° |
| Aperture efficiency | 60 % | 60 % |
| Gain | 55.7 dBi | 57.2 dBi |

HTML pointing guidance: "Position x,y on Moon" of ±0.035°/±0.035° is the worst case for a good tracking system, and ±0.1° for a standard one.

### 11.4 Display helpers

These are needed to reproduce the shown numbers.

- `fformat(x, k)`: rounds to k+1 significant digits, using 10^(k − ⌊lg|x|⌋).
- `fformatDB(x, k)`: shows 10·lg x with k decimals.
- `aformat(x, k)`: rounds to k decimals.

The station presets are written through `fformat(value, 2)` or `fformat(value, 4)`, so a preset value may be rounded to 3 significant digits. For example, the block area 0.3²·π/4 = 0.0706858 becomes 0.0707.

### 11.5 `MoonGlobe.js` / `JKMap.js`

**MoonGlobe** renders an orthographic Moon globe (NASA LRO texture) for TX and RX. The viewing direction comes from (lib_lat, lib_lon) and the sky rotation from `pospara`:

- view = (cos b cos l, cos b sin l, sin b), east = (−sin l, cos l, 0), north = (−sin b cos l, −sin b sin l, cos b);
- sky (X, Y) → (e, n) = R(−pospara)·(X, Y) and depth z = sqrt(1 − X² − Y²);
- point = z·view + e·east + n·north;
- the radius is scaled by diam/0.5°;
- cosmetic limb darkening: 0.82 + 0.18·z.

This is the only "physics" in MoonGlobe, and it is purely visual.

**JKMap** is a canvas plotting and raster helper (`setup`, `put`, `get`, `putIK`, colour bars) with no physics.
---

## 12. Reference values for regression tests

These values were computed by the dossier author. They are evaluations of the formulas exactly as written above, using the JS coefficient tables read as data. They are not outputs taken from the running web page. Use them as first checks for EMELab.

**`attenuation2`**, T = 15 °C, RH = 50 %, P = 980 hPa. Zenith attenuation in dB, with γ in dB/km and h in km:

| f [GHz] | A_zen | γ_o | h_o | γ_w | h_w |
|---|---|---|---|---|---|
| 1.296 | 0.0310 | 0.00561 | 5.508 | 0.00007 | 1.841 |
| 2.32 | 0.0331 | 0.00634 | 5.158 | 0.00022 | 1.842 |
| 3.4 | 0.0343 | 0.00659 | 5.076 | 0.00048 | 1.843 |
| 5.76 | 0.0373 | 0.00690 | 5.031 | 0.00142 | 1.845 |
| 10.368 | 0.0481 | 0.00763 | 5.018 | 0.00527 | 1.854 |
| 24.048 | 0.3764 | 0.01348 | 5.034 | 0.13534 | 2.280 |
| 47.088 | 0.8087 | 0.13088 | 5.042 | 0.08078 | 1.842 |
| 76.032 | 0.8815 | 0.10011 | 5.196 | 0.19634 | 1.841 |
| 122.25 | 2.5492 | 0.25655 | 6.152 | 0.52660 | 1.844 |
| 134.0 | 1.3405 | 0.02517 | 5.610 | 0.64999 | 1.845 |
| 241.92 | 4.3650 | 0.01635 | 5.562 | 2.30946 | 1.851 |

**`solarTemp`**, flux = 0, with a_sun = 0.26667° (so the tan² ratio is 1). The SFU equivalent is T·9.63·tan²a·f².

| f [MHz] | T [K] | SFU equivalent |
|---|---|---|
| 1296 | 118202 | 41 |
| 2320 | 54076 | 61 |
| 3400 | 32365 | 78 |
| 5760 | 15944 | 110 |
| 10368 | 12156 | 273 |
| 24048 | 10672 | 1287 |
| 47088 | 8632 | 3993 |
| 76032 | 7392 | 8914 |
| 122250 | 6619 | 20634 |
| 241920 | 6035 | 73680 |

These differ from the HTML table in §11.1, e.g. 12950 K at 10.368 GHz.

**`getReflectance`** R(f, x) and the normalisation N_R:

| f [GHz] | N_R | R(0) | R(0.2) | R(0.5) | R(0.8) | R(0.9) | R(0.95) | R(0.99) |
|---|---|---|---|---|---|---|---|---|
| 1.296 | 0.03180 | 1 | 0.1553 | 0.02751 | 0.007077 | 0.004327 | 0.002773 | 0.001029 |
| 10.368 | 0.11710 | 1 | 0.458 | 0.1419 | 0.04392 | 0.02867 | 0.02011 | 0.01036 |
| 24.048 | 0.34244 | 1 | 0.7098 | 0.4245 | 0.2537 | 0.2086 | 0.175 | 0.1272 |
| 47.088 | 0.98861 | 1 | 1 | 1 | 0.9995 | 0.9901 | 0.9604 | 0.8888 |
| 76.032 | 0.99642 | 1 | 1 | 1 | 0.9999 | 0.9975 | 0.9902 | 0.9724 |
| 241.92 | 0.99900 | ≈1 | | | | | | |

**Gaussian illumination parameters:**

| T_e [dB] | ρ | η_i | η_s | η_i·η_s | bf | η_MB/η_real (= 0.8899·bf²) |
|---|---|---|---|---|---|---|
| −8 | 0.92120 | 0.9348 | 0.8416 | 0.7867 | 1.11772 | 1.1118 |
| −10 | 1.15150 | 0.9024 | 0.9000 | 0.8122 | 1.14318 | 1.1630 |
| −11 | 1.26665 | 0.8848 | 0.9206 | 0.8145 | 1.15634 | 1.1899 |
| −12 | 1.38180 | 0.8663 | 0.9369 | 0.8117 | 1.16977 | 1.2177 |
| −15 | 1.72725 | 0.8084 | 0.9684 | 0.7828 | 1.21158 | 1.3063 |

**Q65 V2.3 threshold** [dB] vs B4σ [Hz]:

| Mode / profile | 0 | 10 | 50 | 100 | 200 | 400 | 1000 | 1500 |
|---|---|---|---|---|---|---|---|---|
| 60D uniform | −27.80 | −27.19 | −25.06 | −22.91 | −19.58 | −14.91 | −6.64 | −2.26 |
| 60D radial | −27.80 | −27.30 | −25.60 | −23.92 | −21.40 | −17.94 | −12.01 | −8.94 |
| 60E uniform | −27.22 | −26.79 | −25.30 | −23.76 | −21.33 | −17.86 | −11.58 | −8.20 |
| 60E radial | −27.22 | −26.88 | −25.68 | −24.40 | −22.34 | −19.31 | −13.68 | −10.61 |
| 120E uniform | −29.92 | −29.02 | −26.17 | −23.60 | −20.10 | −15.90 | −9.88 | −7.22 |
| 120E radial | −29.92 | −29.27 | −27.08 | −24.93 | −21.71 | −17.33 | −9.87 | −6.02 |

**Legacy Q65 thresholds** [dB] vs mutual spread L [Hz]. For 60D and 120E, L is clamped at 550 Hz.

| L | 60D | 60E | 120E |
|---|---|---|---|
| 0 | −28.29 | −27.48 | −30.75 |
| 50 | −26.55 | −26.41 | −28.94 |
| 100 | −25.10 | −25.44 | −27.35 |
| 200 | −22.88 | −23.81 | −24.77 |
| 400 | −19.97 | −21.46 | −21.35 |
| 550 | −17.80 | −20.23 | −19.60 |
| 800 | −17.80 | −18.69 | −19.60 |
| 1300 | −17.80 | −15.98 | −19.60 |

**Rim-correction exponent** (0.0521/2)·(f/10)^0.21 and regolith absorption coefficient κ:

| f [GHz] | exponent | κ [m⁻¹] |
|---|---|---|
| 10.368 | 0.02625 | 3.8031 |
| 24.048 | 0.03132 | 8.8210 |
| 47.088 | 0.03607 | 17.2723 |
| 76.032 | 0.03989 | 27.8892 |

---

## 13. Implementation notes for EMELab

### 13.1 Dependency map (which models need which inputs)

| Model | Inputs |
|---|---|
| Ephemerides (Sun/Moon RA/Dec, Az/El, distance, phase, Sun direction on disc) | UTC date/time; ΔT = 70 s; station lat/lon from locator; `#station` select (which site's topocentric RA/Dec is used) |
| a_moon, dmoon | Moon geocentric distance; both station positions |
| Libration samples (own algorithm, independent of MoonRaDec) | date/time (minute resolution, ±1 min), each station's lat/lon |
| Locked elevations | ephemerides + GetRefractionRadio(T, RH, P of that station) |
| HPBW | f, D, T_e, shape; η_i,sim for `e`/`x` |
| Gain G | f, D, η_real |
| η_MB | bf(T_e,rx), η_real,rx |
| η_F | RX shape, η_s,sim |
| Disc integrals (BWF, illum, fills, moments) | θ_tx, θ_rx, shapes, offsets, a_moon, a_sun, reflectance mode, f (radial reflectance) |
| Atmosphere | f, T, RH, P per station, cloud loss, elevation |
| Sky/CMB | RX T, A_zen,rx, E_rx, f |
| Spillover | RX D, f/D, offset angle (θ0, ψ_t), E_rx, T_rx,amb, A_zen,rx, shape (`e` → 0), T_add |
| Moon temperature | f, phase (λ☾ − λ☉), Sun direction angle (tilt), a_moon, θ_rx (Gaussian σ), RX offsets, lat tables |
| Sun temperature | f, SFU flux, doy (a_sun), F_sun |
| Signal | P_tx, A_los tx/rx, G_tx, G_rx, ε, λ, dmoon, BWF |
| S/N EME | signal, η_MB, η_F, all temperatures, B, W |
| W | BWF, BWF_ref, moments, libration gradient angle (all four libration samples + pospara) |
| Libration spread / Doppler | four libration samples, f, θ's, offsets, diam |
| Thresholds / margin | mode, S_mut (legacy) or B4σ (V2.3), B, W (CW) |

**Input validity ranges** (`readFields`; outside the range the field turns yellow and the calculation stops, except where noted as warning only):

| Input | Range |
|---|---|
| year | 2000…2100 |
| day | 1…31 |
| f | (1, 350] GHz |
| P_tx | 0…1000 W |
| D | 0.1…100 m |
| offset angle | TX 0…30°, RX 0…50° |
| mesh wire diameter / spacing | 0…30 / 0…100 mm |
| sim efficiencies | 0…1 (warning only) |
| η_real | 0…1 |
| T_e | −30…0 dB |
| x, y offsets | ±0.5° |
| T | −30…40 °C |
| RH | 0…100 % |
| P | 800…1050 hPa |
| cloud loss | TX 0…50, RX 0…20 dB |
| rms | 0…50 mm |
| string gap | 0…50 mm |
| blocking diameter | TX ≤ 3 m, RX ≤ 2 m |
| axial / lateral defocus | 0…200 mm |
| f/D | 0…2 |
| NF | (0, 100] dB |
| B | (0, 100] kHz |
| T_add | −270…200 K |
| flux | 0…500000 SFU |
| manual elevation | TX 0.1…90°, RX 0.1…180° |

### 13.2 Defaults

**HTML defaults** (before the presets are applied):

- year 2017, day 21, 12:00:00 (overwritten by "now" on load); freq 10.368 GHz.
- TX: D 7.2, f/D 0.35, offset 0, rms 0.85, block area 0.3, T_e −11, η_real 0.599, power 38 W, weather 15 °C / 50 % / 980 hPa, elevation 30°.
- RX: D 0.815, f/D 0.66, offset 21°, rms 0.17, block 0, T_e −11, η_real 0.693, NF 0.7 dB, B 2.5 kHz, η_F field 0.85.
- Common: ε 0.075; offsets 0; mesh 0/0; string gap 0; defocus 0; T_add 0; flux 0; cloud 0; CW integration time empty.

**On load** (`window.onload`, l.8051–8085):

- shapes `g`/`g`, reflect `r`, decode `60E`, station `RX`, reflectivity `d` (ε = 0.075), image mode `map`;
- TX preset `6` (DL0SHF 10G, JO54CG13): f 10.368, D 7.2, f/D 0.35, offset 0, rms 0.85, axial 0, block 0.3²·π/4 = 0.0707 m², P_tx 11 W ("instead of 38 W"), η_real 0.599, T_e −11, sim effs 1;
- RX preset `1` (OE2IGL-10, JN67MT87): f 10.368, D 0.815, f/D 0.67, offset 21°, rms 0.17, block 0, η_real 0.69, NF 0.72, T_e −12, sim η_i/η_s/η_pol/η_phase = 0.866/0.869/0.998/0.999, feed "corrug.feed";
- time = now.

The presets do not set shape, weather, offsets or bandwidth. All presets are listed in Appendix A.

### 13.3 Inconsistencies and suspected bugs

1. **TX elevation in Moon/Sun-lock mode uses the wrong topocentric RA/Dec.** `MoonRaDec()` sets RA/Dec topocentric only for the site chosen in the `#station` select (default RX). Then `compute()` sets lat/long to TX and calls `compute1()`, so the TX az/el are computed with the RX-topocentric Moon position. The lunar parallax is up to about 0.95°, so the TX elevation and azimuth error can approach a degree for widely separated stations. In the TX branch the display also shows `rxRtopo` (l.4121–4122).
2. **E_rx ≤ 0 crashes the libration part.** `rxMinus`/`rxPlus`/`txMinus`/`txPlus`, `libGradientAngleDeg` and `emeLibWidthFactor` are assigned only inside `if (rxele > 0)` (l.2441–2555), but they are used unconditionally from l.2647. With E_rx ≤ 0 (possible in locked mode) this is a TypeError. In addition `snrmoon` is undefined, so the margin is NaN.
3. **Initial `elelock = "0"`** is not an option value, so on first load neither manual nor locked elevations are read; 30°/30° is used.
4. **HPBW for shapes `e`/`x`** uses η_i,sim² where the comment implies η_i·η_s (l.2154, 2343).
5. **S/N_EME multiplies the signal by η_MB** in addition to G_rx = η_real·(πD/λ)², and subtracts 10·lg W (a bonus of up to 5·lg(1/BWF) dB with centred beams). This is intentional per the comments ("measured legacy law") but unusual; keep it for compatibility and flag it.
6. **G/T** uses T_moon + T_sky + (η_F − η)T_sky + …, which is inconsistent with the system temperature in the S/N formula: η is missing on T_moon and T_sky, and there is no CMB term.
7. η_F can be smaller than η_MB (e.g. η_real high and T_e strongly negative), which makes the (η_F − η) term negative. There is no guard.
8. The CMB at zenith (skyzenith) reuses T_cmb attenuated with τ at the current elevation, not at the zenith.
9. Spillover:
   - the E > 90° branch for offset dishes is identical to the normal branch;
   - T_spill,0 uses the current-elevation sky temperature;
   - the RX feed tilt for an offset dish equals the half opening angle θ0. **UNCLEAR** whether this is intended (a commented line has ψ_t = ψP).
10. **The calcMoonTemp beam offset is applied in the rotated Sun-aligned frame**, while computeIntegrals applies it in sky X/Y. The Moon-noise beam is always Gaussian, whatever the RX shape. The lunar "lat/lon" of the thermal model are Sun-aligned sky coordinates, not selenographic ones (libration is ignored). The factor 1.07 is unexplained.
11. Grids:
    - computeIntegrals uses x = −0.3 … 0.3 − dr (not centred, offset −dr/2);
    - calcMoonTemp uses −0.3 … 0.3 with N − 1 intervals;
    - both truncate at ±0.3°, so the RX beam outside this square is ignored in S_cmb (unused) and in the Moon noise.
12. The Moon radius a_moon comes from the **geocentric** diameter atan(2R_m/R_geo). The topocentric diameter is computed but only displayed. atan(2R/d) is used instead of 2·asin(R/d) (tiny difference).
13. In `libration()`, cos(asin(b_rad)) is used where cos(b) is intended. Seconds and ΔT are ignored. The ephemeris is independent of MoonRaDec, with a different precision.
14. The libration rate ω uses sqrt(Δb² + Δl²) without the cos b factor, while the gradient angle uses Δl·cos b̄ (inconsistent).
15. The spreading constant 6745.5 Hz/(GHz·°/min) is not derived in the code. 4R_m(π/180/60)/(0.3 m) gives 6738.6.
16. **The margin uses the legacy (DL3WDG) threshold with the uncorrected mutual spread**, clamped at 550 Hz for 60D/120E. The V2.3 threshold is display-only.
17. `getTemp` does not wrap in phase: for p > 70/72 it extrapolates linearly from bins 70–71. p is computed with mod 1 elsewhere.
18. `getReflectance` divides the whole log term by 10, i.e. R = S^0.1·10^(−c x^d/10). It is **UNCLEAR** whether that was intended, but it must be reproduced as is.
19. `GetRefractionRadio2`: `Math.pow` with one argument gives NaN (unused).
20. `attenuation()` (P.676-10, unused):
    - the f ≤ 54 GHz band lacks the rp² factor;
    - in the 54–60 and 62–66 GHz log-Lagrange interpolations the middle term has a + sign. To my knowledge ITU has a −; verify against the Recommendation before using that function.
21. The HTML says refraction is "based on A.L. Berman" and that "constant reflectivity" is the default. The code uses the simplified N/tan(el)·erf model and radial reflectivity by default.
22. The `solarTemp` model values (e.g. 12156 K at 10.368 GHz) do not match the HTML table (12950 K).
23. The max-efficiency formulas differ between shapes: `e` has no mesh term; `x` has no −0.025 add-loss; the add-loss is additive, not a dB loss. They are display-only.
24. `readFields` uses `dmoon` (omegaMoon, unused) before `compute1` has set it on the first call.
25. The libration Doppler uses only x offsets (the y variant is commented out).
26. Locator conversion returns the SW corner of the padded 10-character square (a few hundred metres off centre).
27. Sun fill F_sun assumes the Sun disc is centred on the same grid point as the Moon centre, with the same RX offsets.
28. The noise constants differ: k = 1.38e-23 in kTB and 1.3806e-23 in the Planck CMB formula; c is taken as 0.3 in λ = 0.3/f.
29. `rxetaf` (the η_F input) is read but always overwritten by the shape-dependent value.

### 13.4 Practical recommendation

Implement a "compatibility mode" that reproduces the JS exactly, including items 4, 5, 6, 8, 10, 11, 14, 16 and 18. Fixes such as per-station topocentric positions and a guarded E ≤ 0 path can be offered as options. The order of evaluation matters: BWF and BWF_ref must be normalised before W is computed, and W is used in S/N, CW and the corrected spread.

---

## Appendix A. Station presets (`handletxLocator` l.4344–5815, `handleLocator` l.5817–7277)

Each preset sets only the fields shown. Values are as written in the code, before `fformat` rounding; "·π/4" marks blocking areas given as diameter²·π/4. Commented-out alternative blocks are omitted. The power column is P_tx [W] for TX presets and NF [dB] for RX presets.

### A.1 TX presets (`txlocator` select)

|case|locator|station|freq|txdiam|txftod|txoffang|txrms|txaxi|txblock|txeff|txpower|txedgetap|txsimilleff|txsimspilleff|txsimpoleff|txsimphaseeff|txfeed|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|1|JN67MT87|OE2IGL-10|10.368|0.815|0.67|21|0.17|0|0|0.69|13|-12|0.866|0.869|0.998|0.999|corrug.feed|
|38|JN68XC19|OE2IGL-24|24.048|1.2|0.646|22.8|0.16|0|0|0.73|17|-11.0|0.872|0.931|0.998|0.995|axi-corrug.|
|33|JN68XC19|OE2IGL-76|76.032|1.2|0.646|22.8|0.16|0|0|0.61|0|-12.5|0.857|0.933|0.993|1|Pickett-Potter|
|66|JN67MT87|HiPerf-47|47.088|1.29|0.6|21|0.03|0|0|0.92|40|-11.3|0.960|0.968|1|1|Pickett-Potter|
|65|JN67MT87|HiPerf-76|76.032|1.29|0.6|21|0.03|0|0|0.92|8|-11.3|0.961|0.971|1|1|Pickett-Potter|
|48|IM68BN|CT1BYM-5.7|5.76|1.2|0.646|22.8|0.16|0|0|0.65|120|-11|1.0|1.0|1|1|---|
|43|IM68BN|CT1BYM-10|10.368|1.2|0.646|22.8|0.16|0|0|0.78|38|-11|1.0|1.0|1|1|---|
|52|IM68BN|CT1BYM-24|24.048|1.2|0.646|22.8|0.16|0|0|0.74|25|-11|1.0|1.0|1|1|---|
|2|IM68BN|CT1BYM-47|47.088|1.2|0.646|22.8|0.16|0|0|0.65|18|-13|1.0|1.0|1|1|---|
|34|IM68BN|CT1BYM-76|76.032|1.2|0.646|22.8|0.16|0|0|0.60|0|-11|1.0|1.0|1|1|---|
|73|JO50VJ|DB6NT-10|10.368|3.7|0.35|0|0.5|0|0.2·0.2·π/4|0.55|60|-11|1.0|1.0|1|1|---|
|3|JO50VJ|DB6NT-24|24.048|3.7|0.35|0|0.5|0|0.2·0.2·π/4|0.55|40|-11|1.0|1.0|1|1|---|
|4|JO32SQ|DC1EHG-47|47.088|1.2|0.646|22.8|0.16|0|0|0.65|3|-11|1.0|1.0|1|1|---|
|76|JO32SQ|DC1EHG-76|76.032|1.2|0.646|22.8|0.16|0|0|0.56|0.3|-11|1.0|1.0|1|1|---|
|71|JO62QJ|DC7KY-24|24.048|2.4|0.61|21|0.3|0|0|0.65|120|-11|1.0|1.0|1|1|---|
|5|JO62QJ|DC7KY-47|47.088|2.4|0.61|21|0.3|0|0|0.55|18|-11|1.0|1.0|1|1|---|
|72|JO62QJ|DC7KY-76|76.032|2.4|0.61|21|0.3|0|0|0.3|0.3|-11|1.0|1.0|1|1|---|
|6|JO54CG13|DL0SHF 10G|10.368|7.2|0.35|0|0.85|0|0.3·0.3·π/4|0.599|11|-11|1.0|1.0|1|1|---|
|7|JO62PK|DL7YC-47|47.088|2.4|0.38|0|0.25|0|0.32·0.32·π/4|0.50|42|-12.5|0.862|0.949|0.997|0.982|scalar feed|
|21|JO62PK|DL7YC-76|76.032|2.4|0.38|0|0.25|0|0.2·0.2·π/4|0.41|5|-12|0.863|0.936|0.986|0.998|Cavity feed|
|45|JN11AN|EA3HMJ-10|10.368|0.9|0.66|21|0.17|0|0|0.73|0|-11|1.0|1.0|1|1|---|
|8|JN11AN|EA3HMJ-47|47.088|1.8|0.72|20.1|0.2|0|0|0.60|0|-11|1.0|1.0|1|1|---|
|9|?|?||||||||||||||||
|10|JN87HT|OE4WOG-5.7|5.76|1.8|0.4|0|0.25|0|0.15·0.15·π/4|0.64|30|-11|1.0|1.0|1|1|---|
|67|JN87HT|OE4WOG-10|10.368|1.8|0.7|20|0.25|0|0.15·0.15·π/4|0.64|30|-11|1.0|1.0|1|1|---|
|11|JN78DK75|OE5VRL-10|10.368|3|0.3|0|0.4|0|0.65·0.65·π/4|0.62|20|-11|1.0|1.0|1|1|---|
|25|JN78DK75|OE5VRL-47|47.088|1.2|0.4|0|0.1|0|0.1·0.1|0.62|0|-11|1.0|1.0|1|1|---|
|12|EN19LU|VE4MA-10|10.368|2.4|0.8|21|0.3|0|0|0.72|50|-11|1.0|1.0|1|1|---|
|28|EN19LU|VE4MA-24|24.048|2.4|0.8|21|0.3|0|0|0.72|50|-11|1.0|1.0|1|1|---|
|32|EN19LU|VE4MA-47|47.088|2.4|0.8|21|0.3|0|0|0.55|30|-11|1.0|1.0|1|1|---|
|13|EN13QC|W5LUA-47|47.088|2.4|0.66|21|0.3|0|0.2·0.2·π/4|0.454|28|-11|1.0|1.0|1|1|---|
|55|KO85VS|RW3BP-47|47.088|2.4|0.575|21|0.2|0|0|0.625|30|-15|0.769|0.961|1|1|---|
|14|KO85VS|RW3BP-76|76.032|2.4|0.575|21|0.15|0|0|0.53|8|-11|1.0|1.0|1|1|---|
|15|JO54CG13|DL0SHF 24G|24.048|3.7|0.35|0|0.35|0|0.3·0.3·π/4|0.6|10|-11|1.0|1.0|1|1|---|
|22|JO54CG13|DL0SHF 47G|47.088|3.0|0.35|0|0.3|0|0.3·0.3·π/4|0.5|0|-11|1.0|1.0|1|1|---|
|47|QM05AV|JA1WQF-10|10.368|2.4|0.37|0|0.33|0|0.2·0.2·π/4|0.60|50|-11|1.0|1.0|1|1|---|
|44|QM05AV|JA1WQF-24|24.048|2.4|0.37|0|0.33|0|0.2·0.2·π/4|0.64|23|-11|1.0|1.0|1|1|---|
|16|QM05AV|JA1WQF-47|47.088|2.4|0.37|0|0.33|0|0.2·0.2·π/4|0.45|10|-11|1.0|1.0|1|1|---|
|17|CM87WJ|K6MG-47|47.088|1.8|0.66|21|0.25|0|0|0.695|30|-11|1.0|1.0|1|1|---|
|29|JN79FW|OK1DFC-10|10.368|2.4|0.6|22|0.3|0|0|0.75|55|-13|1.0|1.0|1|1|---|
|57|JN79FW|OK1DFC-24|24.048|2.4|0.6|22|0.3|0|0|0.525|22|-11|1.0|1.0|1|1|---|
|25|JN79FW|OK1DFC-24|24.048|2.4|0.6|22|0.3|0|0|0.375|22|-11|1.0|1.0|1|1|---|
|18|JN79FW|OK1DFC-47|47.088|2.4|0.6|22|0.3|0|0|0.50|45|-15|0.807|0.901|1|1|---|
|19|JN68LM|DL3WDG-10|10.368|2.4|0.8|17.4|0.3|0|0|0.693|75|-11|1.0|1.0||||
|20|JN68LM|DL3WDG-24|24.048|1.2|0.33|0|0.2|0|0|0.60|17|-11|1.0|1.0|1|1|---|
|56|JN68LM|DL3WDG-24|24.048|2.4|0.8|17.4|0.3|0|0|0.3|17|-11|1.0|1.0|1|1|---|
|23|IO90AS|G4RFR-10|10.368|3.65|0.4|0|0.5|0|0.2·0.2·π/4|0.65|200|-11|1.0|1.0|1|1|---|
|24|JO44UW|OZ1LPR-10|10.368|2.4|0.7|21|0.3|0|0|0.70|350|-11|1.0|1.0|1|1|---|
|54|JO44UW|OZ1LPR-24|24.048|2.4|0.7|21|0.3|0|0|0.70|175|-11|1.0|1.0|1|1|---|
|26|JO31FX|PA0BAT-24|24.048|3.7|0.4|0|0.5|0|0.1·0.1·π/4|0.60|11|-11|1.0|1.0|1|1|---|
|41|JO32LR|PA0PLY-10|10.368|3.0|0.3|0|0.4|0|0.2·0.2·π/4|0.55|40|-11|1.0|1.0|1|1|---|
|49|JO22OF|PE1CKK-5.7|5.76|1.8|0.72|20.1|0.25|0|0|0.6|40|-11|1.0|1.0|1|1|---|
|61|JO22OF|PE1CKK-10|10.368|1.8|0.72|20.1|0.25|0|0|0.6|65|-11|1.0|1.0|1|1|---|
|27|JO22OF|PE1CKK-24|24.048|1.8|0.72|20.1|0.25|0|0|0.5|30|-11|1.0|1.0|1|1|---|
|30|IN80AM|EA4LE-10|10.368|1.2|0.646|22.8|0.2|0|0|0.7|0|-11|1.0|1.0|1|1|---|
|31|JN47VK55|OE9ERC-1.3|1.296|10.0|0.414|20|1.8|0|0|0.7|150|-11|1.0|1.0|1|1|---|
|51|JN47VK55|OE9ERC-3.4|3.4|10.0|0.414|20|1.8|0|0|0.475|100|-11|1.0|1.0|1|1|---|
|50|JN47VK55|OE9ERC-5.7|5.76|10.0|0.414|20|1.8|0|0|0.27|65|-11|1.0|1.0|1|1|---|
|40|JN47VK55|OE9ERC-10 10.6m|10.368|10.61|0.414|20.5|0.45|0|1.0|0.451|10|-11|0.617|0.962|1|1|---|
|46|JN47VK55|OE9ERC-10 3.7m|10.368|3.7|0.35|0|0.5|0|0.15·0.15·π/4|0.5|50|-11|1.0|1.0|1|1|---|
|35|KN69OB|UR3VKE-10|10.368|1.8|0.4|0|0.25|0|0|0.7|30|-11|1.0|1.0|1|1|---|
|36|KN69OB|UR3VKE-24|24.048|1.8|0.4|0|0.25|0|0|0.7|30|-11|1.0|1.0|1|1|---|
|37|KN69OB|UR3VKE-47|47.088|1.8|0.4|0|0.25|0|0|0.53|0|-12|0.863|0.915|1|1|---|
|39|JN67MR|OE2JOM-10|10.368|1.82|0.5|27|0.27|0|0|0.6|60|-11|1.0|1.0|1|1|---|
|42|FN54UJ|KA1GT-10|10.368|1.2|0.375|0|0.2|0|0.06·0.06·π/4|0.65|0|-11|1.0|1.0|1|1|---|
|79|JO32ET|PI9RD-1.3|1.296|25|0.48|0|1|0|0.4·0.4·π/4|0.6|0|-10|1|1|1|1|---|
|53|JO32ET|PI9RD-3.4|3.4|25|0.48|0|1|0|0.4·0.4·π/4|0.6|60|-10|0.858|0.906|1|1|---|
|58|JO22MD|PA7JB-10|10.368|2.4|0.6|21|0.3|0|0|0.5|50|-10|1|1|1|1|---|
|59|JN61PM|IZ0JNY-10|10.368|1.2|0.646|22.8|0.2|0|0|0.75|29|-10|1|1|1|1|---|
|62|JN61PM|IZ0JNY-24|24.048|1.2|0.646|22.8|0.2|0|0|0.70|15|-10|1|1|1|1|---|
|68|JN61PM|IZ0JNY-47|47.088|1.2|0.646|22.8|0.2|0|0|0.65|0.1|-10|1|1|1|1|---|
|60|JN72DJ|I6YPK-10|10.368|1.0|0.66|21|0.18|0|0|0.60|25|-10|1|1|1|1|---|
|63|JN79DW|OK1KIR-24|24.048|4.5|0.42|0|0.5|0|0.2·0.2·π/4|0.55|20|-10|1|1|1|1|---|
|64|JN48SW|DL6SH-10|10.368|2.4|0.70|21.3|0.35|0|0.3·0.3·π/4|0.67|50|-10|0.79|0.982|1|1|Scalar feed|
|69|KN33NG|LZ4OC-24|24.048|1.5|0.66|21.3|0.22|0|0|0.56|20|-10|1|1|1|1|---|
|70|KN33NG|LZ4OC-10|10.368|1.8|0.51|21.0|0.25|0|0|0.65|20|-10|1|1|1|1|---|
|82|KN33NG|LZ4OC-47|47.088|1.2|0.646|22.8|0.16|0|0|0.61|0|-10|1|1|1|1|---|
|74|JO20ES|ON5TA-10|10.368|2.4|0.6|21.0|0.3|0|0|0.65|30|-10|1|1|1|1|---|
|75|DM42LM|NJ6D-10|10.368|0.76|0.7|21.0|0.15|0|0|0.65|10|-10|1|1|1|1|---|
|77|IN50RO|CT1DMK-47|47.088|2.4|0.6|21.0|0.3|0|0|0.5|0|-10|1|1|1|1|---|
|78|JO89TT|SA5IKN-10|10.368|0.9|0.66|21.0|0.17|0|0|0.6|27|-10|1|1|1|1|---|
|80|JN46WE|IW2FZR-10|10.368|1.8|0.41|0|0.5|0|0.014|0.5|35|-10|1|1|1|1|---|
|81|JN46WE|IW2FZR-24|24.048|1.8|0.41|0|0.5|0|0.014|0.5|1|-10|1|1|1|1|---|
|83|JN36BF|4U1ITU-10|10.368|1.2|0.646|22.8|0.16|0|0.0|0.65|25|-10|1|1|1|1|---|

### A.2 RX presets (`rxlocator` select)

|case|locator|station|freq|rxdiam|rxftod|rxoffang|rxrms|rxaxi|rxblock|rxeff|rxnf|rxedgetap|rxsimilleff|rxsimspilleff|rxsimpoleff|rxsimphaseeff|rxfeed|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|1|JN67MT87|OE2IGL-10|10.368|0.815|0.67|21|0.17|0|0|0.69|0.72|-12|0.866|0.869|0.998|0.999|corrug.feed|
|38|JN68XC19|OE2IGL-24|24.048|1.2|0.646|22.8|0.16|0|0|0.73|1.40|-11.0|0.872|0.931|0.998|0.995|axi-corrug.|
|33|JN68XC19|OE2IGL-76|76.032|1.2|0.646|22.8|0.16|0|0|0.61|7.0|-12.2|0.857|0.933|0.993|1|Pickett-Potter|
|66|JN67MT87|Hiperf-47|47.088|1.29|0.6|21|0.03|0|0|0.92|1.3|-11.3|0.960|0.968|1|1|Pickett-Potter|
|65|JN67MT87|Hiperf-76|76.032|1.29|0.6|21|0.03|0|0|0.92|2.5|-11.3|0.961|0.971|1|1|Pickett-Potter|
|48|IM68BN|CT1BYM-5.7|5.76|1.2|0.646|22.8|0.16|0|0|0.65|0.4|-11|1.0|1.0|1|1|---|
|43|IM68BN|CT1BYM-10|10.368|1.2|0.646|22.8|0.16|0|0|0.78|0.6|-11|1.0|1.0|1|1|---|
|52|IM68BN|CT1BYM-24|24.048|1.2|0.646|22.8|0.16|0|0|0.74|1.8|-11|1.0|1.0|1|1|---|
|2|IM68BN|CT1BYM-47|47.088|1.2|0.646|22.8|0.16|0|0|0.65|1.9|-13|1.0|1.0|1|1|---|
|34|IM68BN|CT1BYM-76|76.032|1.2|0.646|22.8|0.16|0|0|0.60|5.1|-11|1.0|1.0|1|1|---|
|73|JO50VJ|DB6NT-10|10.368|3.7|0.35|0|0.5|0|0.2·0.2·π/4|0.55|0.65|-11|1.0|1.0|1|1|---|
|3|JO50VJ|DB6NT-24|24.048|3.7|0.35|0|0.5|0|0.2·0.2·π/4|0.55|1.3|-11|1.0|1.0|1|1|---|
|4|JO32SQ|DC1EHG-47|47.088|1.2|0.646|22.8|0.16|0|0|0.65|2.95|-11|1.0|1.0|1|1|---|
|76|JO32SQ|DC1EHG-76|76.032|1.2|0.646|22.8|0.16|0|0|0.56|4.8|-11|1.0|1.0|1|1|---|
|71|JO62QJ|DC7KY-24|24.048|2.4|0.61|21|0.3|0|0|0.65|1.6|-11|1.0|1.0|1|1|---|
|5|JO62QJ|DC7KY-47|47.088|2.4|0.61|21|0.3|0|0|0.55|1.9|-11|1.0|1.0|1|1|---|
|72|JO62QJ|DC7KY-76|76.032|2.4|0.61|21|0.3|0|0|0.3|2.65|-11|1.0|1.0|1|1|---|
|6|JO54CG13|DL0SHF 10G|10.368|7.2|0.35|0|0.85|0|0.3·0.3·π/4|0.599|99|-11|1.0|1.0|1|1|---|
|7|JO62PK|DL7YC-47|47.088|2.4|0.38|0|0.25|0|0.32·0.32·π/4|0.50|1.28|-12.5|0.862|0.949|0.997|0.982|scalar feed|
|21|JO62PK|DL7YC-76|76.032|2.4|0.38|0|0.25|0|0.2·0.2·π/4|0.41|2.3|-12|0.863|0.936|0.986|0.998|Cavity feed|
|45|JN11AN|EA3HMJ-10|10.368|0.9|0.66|21|0.17|0|0|0.73|1.1|-11|1.0|1.0|1|1|---|
|8|JN11AN|EA3HMJ-47|47.088|1.8|0.72|20.1|0.2|0|0|0.60|1.9|-11|1.0|1.0|1|1|---|
|9|?|?||||||||||||||||
|10|JN87HT|OE4WOG-5.7|5.76|1.8|0.4|0|0.25|0|0.15·0.15·π/4|0.64|0.8|-11|1.0|1.0|1|1|---|
|67|JN87HT|OE4WOG-10|10.368|1.8|0.7|20|0.25|0|0.15·0.15·π/4|0.64|0.7|-11|1.0|1.0|1|1|---|
|11|JN78DK75|OE5VRL-10|10.368|3|0.3|0|0.4|0|0.65·0.65·π/4|0.62|0.9|-11|1.0|1.0|1|1|---|
|25|JN78DK75|OE5VRL-47|47.088|1.2|0.4|0|0.1|0|0.1·0.1|0.62|5.7|-11|1.0|1.0|1|1|---|
|12|EN19LU|VE4MA-10|10.368|2.4|0.8|21|0.3|0|0|0.72|0.6|-11|1.0|1.0|1|1|---|
|28|EN19LU|VE4MA-24|24.048|2.4|0.8|21|0.3|0|0|0.72|1.2|-11|1.0|1.0|1|1|---|
|32|EN19LU|VE4MA-47|47.088|2.4|0.8|21|0.3|0|0|0.55|2.1|-11|1.0|1.0|1|1|---|
|13|EN13QC|W5LUA-47|47.088|2.4|0.66|21|0.3|0|0.2·0.2·π/4|0.454|4.0|-11|1.0|1.0|1|1|---|
|55|KO85VS|RW3BP-47|47.088|2.4|0.575|21|0.2|0|0|0.625|1.25|-15|0.769|0.961|1|1|---|
|14|KO85VS|RW3BP-76|76.032|2.4|0.575|21|0.15|0|0|0.53|2.2|-11|1.0|1.0|1|1|---|
|15|JO54CG13|DL0SHF 24G|24.048|3.7|0.35|0|0.35|0|0.3·0.3·π/4|0.6|1.5|-11|1.0|1.0|1|1|---|
|22|JO54CG13|DL0SHF 47G|47.088|3.0|0.35|0|0.3|0|0.3·0.3·π/4|0.5|3.6|-11|1.0|1.0|1|1|---|
|47|QM05AV|JA1WQF-10|10.368|2.4|0.37|0|0.33|0|0.2·0.2·π/4|0.60|0.7|-11|1.0|1.0|1|1|---|
|44|QM05AV|JA1WQF-24|24.048|2.4|0.37|0|0.33|0|0.2·0.2·π/4|0.64|1.5|-11|1.0|1.0|1|1|---|
|16|QM05AV|JA1WQF-47|47.088|2.4|0.37|0|0.33|0|0.2·0.2·π/4|0.45|1.9|-11|1.0|1.0|1|1|---|
|17|CM87WJ|K6MG-47|47.088|1.8|0.66|21|0.25|0|0|0.695|1.5|-11|1.0|1.0|1|1|---|
|29|JN79FW|OK1DFC-10|10.368|2.4|0.6|22|0.3|0|0|0.75|0.7|-13|1.0|1.0|1|1|---|
|57|JN79FW|OK1DFC-24|24.048|2.4|0.6|22|0.3|0|0|0.525|1.7|-11|1.0|1.0|1|1|---|
|25|JN79FW|OK1DFC-24|24.048|2.4|0.6|22|0.3|0|0|0.375|1.1|-11|1.0|1.0|1|1|---|
|18|JN79FW|OK1DFC-47|47.088|2.4|0.6|22|0.3|0|0|0.50|2.6|-15|0.807|0.901|1|1|---|
|19|JN68LM|DL3WDG-10|10.368|2.4|0.8|17.4|0.3|0|0|0.693|0.6|-11|1.0|1.0|1|1|---|
|20|JN68LM|DL3WDG-24|24.048|1.2|0.33|0|0.2|0|0|0.60|2.3|-11|1.0|1.0|1|1|---|
|56|JN68LM|DL3WDG-24|24.048|2.4|0.8|17.4|0.3|0|0|0.3|2.3|-11|1.0|1.0|1|1|---|
|23|IO90AS|G4RFR-10|10.368|3.65|0.4|0|0.5|0|0.2·0.2·π/4|0.65|0.8|-11|1.0|1.0|1|1|---|
|24|JO44UW|OZ1LPR-10|10.368|2.4|0.7|21|0.3|0|0|0.70|0.82|-11|1.0|1.0|1|1|---|
|54|JO44UW|OZ1LPR-24|24.048|2.4|0.7|21|0.3|0|0|0.70|1.6|-11|1.0|1.0|1|1|---|
|26|JO31FX|PA0BAT-24|24.048|3.7|0.4|0|0.5|0|0.1·0.1·π/4|0.6|1.8|-11|1.0|1.0|1|1|---|
|41|JO32LR|PA0PLY-10|10.368|3.0|0.3|0|0.4|0|0.2·0.2·π/4|0.55|0.5|-11|1.0|1.0|1|1|---|
|49|JO22OF|PE1CKK-5.76|5.76|1.8|0.72|20.1|0.25|0|0|0.6|0.7|-11|1.0|1.0|1|1|---|
|61|JO22OF|PE1CKK-10|10.368|1.8|0.72|20.1|0.25|0|0|0.6|0.7|-11|1.0|1.0|1|1|---|
|27|JO22OF|PE1CKK-24|24.048|1.8|0.72|20.1|0.25|0|0|0.5|1.5|-11|1.0|1.0|1|1|---|
|30|IN80AM|EA4LE-10|10.368|1.2|0.646|22.8|0.2|0|0|0.7|0.8|-11|1.0|1.0|1|1|---|
|31|JN47VK55|OE9ERC-1.3|1.296|10.0|0.414|20|1.8|0|0|0.7|0.35|-11|1.0|1.0|1|1|---|
|51|JN47VK55|OE9ERC-3.4|3.4|10.0|0.414|20|1.8|0|0|0.475|0.52|-11|1.0|1.0|1|1|---|
|50|JN47VK55|OE9ERC-5.7|5.76|10.0|0.414|20|1.8|0|0|0.27|0.6|-11|1.0|1.0|1|1|---|
|40|JN47VK55|OE9ERC-10 10.6m|10.368|10.61|0.414|20.5|0.45|0|1.0|0.451|0.7|-11|0.617|0.962|1|1|---|
|46|JN47VK55|OE9ERC-10 3.7m|10.368|3.7|0.35|0|0.5|0|0.15·0.15·π/4|0.5|0.7|-11|1.0|1.0|1|1|---|
|35|KN69OB|UR3VKE-10|10.368|1.8|0.4|0|0.25|0|0|0.7|0.7|-11|1.0|1.0|1|1|---|
|36|KN69OB|UR3VKE-24|24.048|1.8|0.4|0|0.25|0|0|0.7|0.7|-11|1.0|1.0|1|1|---|
|37|KN69OB|UR3VKE-47|47.088|1.8|0.4|0|0.25|0|0|0.53|3.3|-12|0.863|0.915|1|1|---|
|39|JN67MR|OE2JOM-10|10.368|1.82|0.5|27|0.27|0|0|0.6|0.75|-11|1.0|1.0|1|1|---|
|42|FN54UJ|KA1GT-10|10.368|1.2|0.375|0|0.2|0|0.06·0.06·π/4|0.65|0.8|-11|1.0|1.0|1|1|---|
|79|JO32ET|PI9RD-1.3|1.296|25|0.48|0|1|0|0.4·0.4·π/4|0.6|0.45|-10|1|1|1|1|---|
|53|JO32ET|PI9RD-3.4|3.4|25|0.48|0|1|0|0.4·0.4·π/4|0.6|0.55|-10|0.858|0.906|1|1|---|
|58|JO22MD|PA7JB-10|10.368|2.4|0.6|21|0.3|0|0|0.5|0.65|-10|1|1|1|1|---|
|59|JN61PM|IZ0JNY-10|10.368|1.2|0.646|22.8|0.2|0|0|0.75|0.6|-10|1|1|1|1|---|
|62|JN61PM|IZ0JNY-24|24.048|1.2|0.646|22.8|0.2|0|0|0.70|1.4|-10|1|1|1|1|---|
|68|JN61PM|IZ0JNY-47|47.088|1.2|0.646|21|0.2|0|0|0.65|2.0|-10|1|1|1|1|---|
|60|JN72DJ|I6YPK-10|10.368|1.0|0.66|21|0.18|0|0|0.60|0.65|-10|1|1|1|1|---|
|63|JN79DW|OK1KIR-24|24.048|4.5|0.42|0|0.5|0|0.2·0.2·π/4|0.55|1.4|-10|1|1|1|1|---|
|64|JN48SW|DL6SH-10|10.368|2.4|0.70|21.3|0.35|0|0.3·0.3·π/4|0.67|0.65|-10|0.79|0.982|1|1|Scalar feed|
|69|KN33NG|LZ4OC-24|24.048|1.5|0.66|21.3|0.22|0|0|0.56|1.4|-10|1|1|1|1|---|
|70|KN33NG|LZ4OC-10|10.368|1.8|0.51|21.0|0.25|0|0|0.65|0.65|-10|1|1|1|1|---|
|82|KN33NG|LZ4OC-47|47.088|1.2|0.646|22.8|0.16|0|0|0.61|2.5|-10|1|1|1|1|---|
|74|JO20ES|ON5ST-10|10.368|2.4|0.6|21.0|0.3|0|0|0.65|0.65|-10|1|1|1|1|---|
|75|DM42LM|NJ6D-10|10.368|0.76|0.7|21.0|0.15|0|0|0.65|1.8|-10|1|1|1|1|---|
|77|IN50RO|CT1DMK-47|47.088|2.4|0.6|21.0|0.3|0|0|0.5|4.3|-10|1|1|1|1|---|
|78|JO89TT|SA5IKN-10|10.368|0.9|0.66|21.0|0.17|0|0|0.6|0.65|-10|1|1|1|1|---|
|80|JN46WE|IW2FZR-10|10.368|1.8|0.41|0|0.5|0|0.014|0.5|1.1|-10|1|1|1|1|---|
|81|JN46WE|IW2FZR-24|24.048|1.8|0.41|0|0.5|0|0.014|0.5|1.5|-10|1|1|1|1|---|
|83|JN36BF|4U1ITU-10|10.368|1.2|0.646|22.8|0.16|0|0.0|0.65|0.75|-10|1|1|1|1|---|

Notes: case "0" (not listed) means manual locator entry and clears lat/lon. In the RX table the `rxnf` column is the receiver noise figure in dB; the TX table has `txpower` [W] in that position. Several stations appear with more than one dish or band, under different case numbers.
