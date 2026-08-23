#!/usr/bin/env python3
"""
GNSS Performance Analysis Dashboard
Plots HDOP, satellite count, TTF, per-satellite SNR, altitude and more
from telemetry_data.json — filtered to Jan 7-8, 2026
"""

import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ── Load data ────────────────────────────────────────────────────────────────
with open('/home/englotk/working/noaa/ground/data/telemetry_data.json') as f:
    data = json.load(f)

# Parse timestamps
for r in data:
    ts = r['timestamp']
    if ts.endswith('+00:00'):
        ts = ts.replace('+00:00', '+0000')
    r['dt'] = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f%z')

# ── Filter to Jan 7-8 only ──────────────────────────────────────────────────
start = datetime(2026, 1, 7, tzinfo=timezone.utc)
end   = datetime(2026, 1, 9, tzinfo=timezone.utc)
data = [r for r in data if start <= r['dt'] < end]
data.sort(key=lambda r: r['dt'])

# Remove known outliers: altitude=0 (bad GPS) and HDOP=25.5 (spurious)
data = [r for r in data if r.get('altitude', 1) != 0.0]
data = [r for r in data if r.get('hdop', 0) < 25]
print(f"Filtered to {len(data)} records (Jan 7-8, outliers removed)")

times = [r['dt'] for r in data]

# ── Extract series ───────────────────────────────────────────────────────────
satellites = [r.get('satellites') for r in data]
hdop = [r.get('hdop') for r in data]
ttf = [r.get('ttf_seconds') for r in data]
altitude = [r.get('altitude') for r in data]

# gnss_detail fields
sats_used = []
gps_count = []
glonass_count = []
beidou_count = []
other_count = []

gnss_times = []
all_gps_snr = []

for r in data:
    gd = r.get('gnss_detail')
    if gd:
        gnss_times.append(r['dt'])
        sats_used.append(gd.get('satellites_used'))
        gps_count.append(gd.get('gps_count', 0) or 0)
        glonass_count.append(gd.get('glonass_count', 0) or 0)
        beidou_count.append(gd.get('beidou_count', 0) or 0)
        other_count.append(gd.get('other_count', 0) or 0)

        for sat in gd.get('gps_satellites', []):
            if sat['prn'] <= 32:
                all_gps_snr.append((r['dt'], sat['prn'], sat['snr']))

# ── Create figure ────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(22, 34))
fig.suptitle('GNSS Performance Dashboard\nstrato3 · Jan 7–8, 2026',
             fontsize=18, fontweight='bold', y=0.995)

gs = fig.add_gridspec(8, 2, hspace=0.45, wspace=0.3,
                      left=0.07, right=0.95, top=0.97, bottom=0.02)

date_fmt = mdates.DateFormatter('%b %d\n%H:%M')

def style_ax(ax, ylabel, title=None):
    ax.xaxis.set_major_formatter(date_fmt)
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
    ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    ax.set_ylabel(ylabel, fontsize=11)
    if title:
        ax.set_title(title, fontsize=13, fontweight='bold', pad=8)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=9)
    ax.set_xlim(start, end)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Altitude over time (full width) — colored by HDOP
# ═══════════════════════════════════════════════════════════════════════════════
ax_alt = fig.add_subplot(gs[0, :])
valid_alt = [(t, a) for t, a in zip(times, altitude) if a is not None]
if valid_alt:
    at, av = zip(*valid_alt)
    av_arr = np.array(av)
    hdop_for_alt = []
    for t, a in zip(times, altitude):
        if a is not None:
            idx = times.index(t)
            h = hdop[idx]
            hdop_for_alt.append(h if h is not None else np.nan)
    hdop_arr = np.array(hdop_for_alt)
    mask_valid = ~np.isnan(hdop_arr)

    ax_alt.plot(at, av, '-', color='#2c3e50', lw=1.5, alpha=0.5, zorder=1)
    sc = ax_alt.scatter([at[i] for i in range(len(at)) if mask_valid[i]],
                        av_arr[mask_valid],
                        c=hdop_arr[mask_valid], cmap='RdYlGn_r',
                        vmin=0.5, vmax=7, s=18, alpha=0.8, edgecolors='none', zorder=2)
    cax = ax_alt.inset_axes([1.01, 0.1, 0.012, 0.8])
    cbar = plt.colorbar(sc, cax=cax)
    cbar.set_label('HDOP', fontsize=10)
    ax_alt.axhline(y=1089, color='#e74c3c', ls='--', lw=2, alpha=0.8, label='Actual: 1089 m')
    ax_alt.legend(loc='lower left', fontsize=9)
    ax_alt.set_ylim(1040, 1100)
style_ax(ax_alt, 'Altitude (m)', 'Altitude Profile (colored by HDOP quality)')

# ═══════════════════════════════════════════════════════════════════════════════
# 2. HDOP over time (full width) — linear scale, max 20
# ═══════════════════════════════════════════════════════════════════════════════
ax1 = fig.add_subplot(gs[1, :])
valid_hdop = [(t, h) for t, h in zip(times, hdop) if h is not None]
if valid_hdop:
    ht, hv = zip(*valid_hdop)
    hv_arr = np.array(hv)
    ax1.scatter(ht, hv, c=np.where(hv_arr <= 1.0, '#2ecc71',
                                    np.where(hv_arr <= 2.0, '#27ae60',
                                    np.where(hv_arr <= 5.0, '#f39c12',
                                    np.where(hv_arr <= 10.0, '#e67e22', '#e74c3c')))),
                s=14, alpha=0.7, edgecolors='none')
ax1.axhline(y=1.0, color='#2ecc71', ls='--', alpha=0.5, label='Ideal (≤1)')
ax1.axhline(y=2.0, color='#27ae60', ls='--', alpha=0.5, label='Excellent (≤2)')
ax1.axhline(y=5.0, color='#f39c12', ls='--', alpha=0.5, label='Good (≤5)')
ax1.set_ylim(0, 7)
style_ax(ax1, 'HDOP', 'Horizontal Dilution of Precision (HDOP)')
ax1.legend(loc='upper right', fontsize=9, ncol=2)

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Satellite count over time (stacked by constellation)
# ═══════════════════════════════════════════════════════════════════════════════
ax2 = fig.add_subplot(gs[2, :])
if gnss_times:
    gt = gnss_times
    gps_arr = np.array(gps_count, dtype=float)
    glo_arr = np.array(glonass_count, dtype=float)
    bei_arr = np.array(beidou_count, dtype=float)
    oth_arr = np.array(other_count, dtype=float)

    ax2.fill_between(gt, 0, gps_arr, alpha=0.6, color='#3498db', label='GPS', step='mid')

    su_valid = [(t, s) for t, s in zip(gnss_times, sats_used) if s is not None]
    if su_valid:
        sut, suv = zip(*su_valid)
        ax2.plot(sut, suv, 'k-', lw=1.2, alpha=0.8, label='Used in fix')

    ax2.axhline(y=4, color='red', ls=':', alpha=0.6, label='Minimum for 3D fix')
    ax2.set_ylim(0, max(max(gps_arr), 12) + 1)
style_ax(ax2, 'Satellite Count', 'Satellites in View')
ax2.legend(loc='upper right', fontsize=9, ncol=3)

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Altitude & HDOP twin-axis time series
# ═══════════════════════════════════════════════════════════════════════════════
ax_twin = fig.add_subplot(gs[3, :])
valid_alt2 = [(t, a) for t, a in zip(times, altitude) if a is not None]
if valid_alt2:
    at2, av2 = zip(*valid_alt2)
    ax_twin.plot(at2, av2, '-', color='#2c3e50', lw=1.5, alpha=0.8, label='Altitude')
    ax_twin.axhline(y=1089, color='#2c3e50', ls=':', lw=1.5, alpha=0.5, label='Actual: 1089 m')
    ax_twin.set_ylabel('Altitude (m)', fontsize=11, color='#2c3e50')
    ax_twin.tick_params(axis='y', labelcolor='#2c3e50')

ax_twin2 = ax_twin.twinx()
valid_hdop2 = [(t, h) for t, h in zip(times, hdop) if h is not None]
if valid_hdop2:
    ht2, hv2 = zip(*valid_hdop2)
    ax_twin2.plot(ht2, hv2, '-', color='#e74c3c', lw=1, alpha=0.7, label='HDOP')
    ax_twin2.scatter(ht2, hv2, c='#e74c3c', s=8, alpha=0.5, edgecolors='none')
    ax_twin2.set_ylabel('HDOP', fontsize=11, color='#e74c3c')
    ax_twin2.tick_params(axis='y', labelcolor='#e74c3c')
    ax_twin2.set_ylim(0, 7)

style_ax(ax_twin, '', 'Altitude & HDOP Correlation Over Time')
lines1, labels1 = ax_twin.get_legend_handles_labels()
lines2, labels2 = ax_twin2.get_legend_handles_labels()
ax_twin.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=9)

# ═══════════════════════════════════════════════════════════════════════════════
# 5. Time to First Fix (TTF)
# ═══════════════════════════════════════════════════════════════════════════════
ax4 = fig.add_subplot(gs[4, :])
# Build TTF data with satellite count for coloring
valid_ttf_data = [(t, v, s) for t, v, s in zip(times, ttf, satellites) 
                  if v is not None and v > 0 and s is not None]
if valid_ttf_data:
    tt, tv, ts_sats = zip(*valid_ttf_data)
    tv_arr = np.array(tv)
    ts_sats_arr = np.array(ts_sats)
    sc_ttf = ax4.scatter(tt, tv, c=ts_sats_arr, cmap='RdYlGn', 
                         vmin=0, vmax=11, s=16, alpha=0.7, edgecolors='none')
    cax_ttf = ax4.inset_axes([1.01, 0.1, 0.012, 0.8])
    cbar_ttf = plt.colorbar(sc_ttf, cax=cax_ttf)
    cbar_ttf.set_label('Satellites', fontsize=10)
    ax4.axhline(y=np.median(tv_arr), color='#3498db', ls='--', alpha=0.7,
                label=f'Median: {np.median(tv_arr):.1f}s')
    ax4.legend(fontsize=9)
style_ax(ax4, 'TTF (seconds)', 'Time to Fix (TTF)')

# ═══════════════════════════════════════════════════════════════════════════════
# 6. Per-satellite GPS SNR heatmap
# ═══════════════════════════════════════════════════════════════════════════════
ax5 = fig.add_subplot(gs[5, :])
if all_gps_snr:
    gps_t, gps_prn, gps_snr = zip(*all_gps_snr)
    gps_snr_arr = np.array(gps_snr, dtype=float)
    sc = ax5.scatter(gps_t, gps_prn, c=gps_snr_arr, cmap='RdYlGn',
                     vmin=0, vmax=45, s=14, alpha=0.8, edgecolors='none')
    cax5 = ax5.inset_axes([1.01, 0.1, 0.012, 0.8])
    cbar = plt.colorbar(sc, cax=cax5)
    cbar.set_label('C/N₀ (dB-Hz)', fontsize=10)
    ax5.set_yticks(sorted(set(gps_prn)))
style_ax(ax5, 'GPS PRN', 'GPS Satellite Signal Strength (C/N₀)')

# ═══════════════════════════════════════════════════════════════════════════════
# 7. Scatter plots + Histograms + Summary
# ═══════════════════════════════════════════════════════════════════════════════

# HDOP vs Altitude (colored by satellite count)
ax6 = fig.add_subplot(gs[6, 0])
valid_ahs = [(r.get('altitude'), r.get('hdop'), r.get('satellites')) for r in data 
             if r.get('altitude') is not None and r.get('hdop') is not None and r.get('satellites') is not None]
if valid_ahs:
    a_vals, h_vals, s_vals = zip(*valid_ahs)
    sc6 = ax6.scatter(a_vals, h_vals, c=s_vals, cmap='RdYlGn', vmin=0, vmax=11,
                      alpha=0.6, s=22, edgecolors='none')
    cbar6 = plt.colorbar(sc6, ax=ax6, pad=0.02, shrink=0.8)
    cbar6.set_label('Satellites', fontsize=9)
ax6.axvline(x=1089, color='#e74c3c', ls='--', lw=1.5, alpha=0.7, label='Actual: 1089 m')
ax6.legend(fontsize=9)
ax6.set_ylim(0, 7)
ax6.set_xlabel('Altitude (m)', fontsize=11)
ax6.set_ylabel('HDOP', fontsize=11)
ax6.set_title('Altitude vs HDOP (colored by sats)', fontsize=13, fontweight='bold', pad=8)
ax6.grid(True, alpha=0.3)

# Summary statistics
ax11 = fig.add_subplot(gs[6, 1])
ax11.axis('off')

valid_h = [h for h in hdop if h is not None]
valid_s = [s for s in satellites if s is not None]
valid_t = [t for t in ttf if t is not None and t > 0]
valid_a = [a for a in altitude if a is not None]

has_beidou = sum(1 for b in beidou_count if b > 0)
has_glonass = sum(1 for g in glonass_count if g > 0)

stats_text = (
    f"━━━━  GNSS Performance Summary  ━━━━\n"
    f"━━━━     Jan 7–8, 2026 only      ━━━━\n\n"
    f"  Records:        {len(data)} total, {len(gnss_times)} w/ GNSS detail\n\n"
    f"  Altitude (actual: 1089 m):\n"
    f"    Min:          {min(valid_a):.0f} m\n"
    f"    Max:          {max(valid_a):.0f} m\n"
    f"    Mean error:   {np.mean(np.array(valid_a) - 1089):.1f} m\n"
    f"    Std dev:      {np.std(np.array(valid_a)):.1f} m\n\n"
    f"  HDOP:\n"
    f"    Median:       {np.median(valid_h):.1f}\n"
    f"    Mean:         {np.mean(valid_h):.1f}\n"
    f"    ≤ 2.0:        {sum(1 for h in valid_h if h <= 2.0)} ({sum(1 for h in valid_h if h <= 2.0)/len(valid_h)*100:.0f}%)\n"
    f"    ≤ 5.0:        {sum(1 for h in valid_h if h <= 5.0)} ({sum(1 for h in valid_h if h <= 5.0)/len(valid_h)*100:.0f}%)\n"
    f"    > 10.0:       {sum(1 for h in valid_h if h > 10.0)} ({sum(1 for h in valid_h if h > 10.0)/len(valid_h)*100:.0f}%)\n\n"
    f"  Satellites:\n"
    f"    Median:       {np.median(valid_s):.0f}\n"
    f"    Mean:         {np.mean(valid_s):.1f}\n"
    f"    Max:          {max(valid_s):.0f}\n"
    f"    Zero sats:    {sum(1 for s in valid_s if s == 0)} ({sum(1 for s in valid_s if s == 0)/len(valid_s)*100:.0f}%)\n\n"
    f"  Time to Fix:\n"
    f"    Median:       {np.median(valid_t):.1f}s\n"
    f"    Mean:         {np.mean(valid_t):.1f}s\n"
    f"    < 10s:        {sum(1 for t in valid_t if t < 10)} ({sum(1 for t in valid_t if t < 10)/len(valid_t)*100:.0f}%)\n"
    f"    > 30s:        {sum(1 for t in valid_t if t > 30)} ({sum(1 for t in valid_t if t > 30)/len(valid_t)*100:.0f}%)\n"
)

ax11.text(0.05, 0.95, stats_text, transform=ax11.transAxes,
          fontsize=10, verticalalignment='top', fontfamily='monospace',
          bbox=dict(boxstyle='round,pad=0.5', facecolor='#ecf0f1', alpha=0.8))

# ═══════════════════════════════════════════════════════════════════════════════
# 8. CEP (Circular Error Probable) — position error from median
# ═══════════════════════════════════════════════════════════════════════════════

# Compute position errors relative to median lat/lon (in meters)
valid_pos = [(r['latitude'], r['longitude'], r.get('hdop')) 
             for r in data if r.get('latitude') is not None and r.get('longitude') is not None
             and r['latitude'] != 0 and r['longitude'] != 0]

if valid_pos:
    lats = np.array([p[0] for p in valid_pos])
    lons = np.array([p[1] for p in valid_pos])
    hdops_pos = np.array([p[2] if p[2] is not None else np.nan for p in valid_pos])
    
    # Median as reference point
    med_lat = np.median(lats)
    med_lon = np.median(lons)
    
    # Convert to meters (approximate at this latitude)
    lat_m_per_deg = 111320.0  # meters per degree latitude
    lon_m_per_deg = 111320.0 * np.cos(np.radians(med_lat))  # meters per degree longitude
    
    east_err = (lons - med_lon) * lon_m_per_deg   # East error in meters
    north_err = (lats - med_lat) * lat_m_per_deg  # North error in meters
    radial_err = np.sqrt(east_err**2 + north_err**2)  # Radial error
    
    # CEP calculations
    cep50 = np.percentile(radial_err, 50)
    cep95 = np.percentile(radial_err, 95)
    cep99 = np.percentile(radial_err, 99)
    rms_err = np.sqrt(np.mean(radial_err**2))
    
    # CEP 2D density plot (left) — hexbin to handle quantized lat/lon
    ax_cep = fig.add_subplot(gs[7, 0])
    ax_cep.set_aspect('equal')
    
    lim = max(cep95 * 1.3, 10)
    hb = ax_cep.hexbin(east_err, north_err, gridsize=25, cmap='YlOrRd',
                       mincnt=1, extent=(-lim, lim, -lim, lim))
    cbar = plt.colorbar(hb, ax=ax_cep, pad=0.02, shrink=0.8)
    cbar.set_label('Point density', fontsize=9)
    
    # Draw CEP circles
    theta = np.linspace(0, 2*np.pi, 100)
    ax_cep.plot(cep50 * np.cos(theta), cep50 * np.sin(theta), 
                'b--', lw=1.5, alpha=0.7, label=f'CEP50: {cep50:.1f} m')
    ax_cep.plot(cep95 * np.cos(theta), cep95 * np.sin(theta), 
                'r--', lw=1.5, alpha=0.7, label=f'CEP95: {cep95:.1f} m')
    
    # Crosshair at center
    lim = max(cep95 * 1.3, 10)
    ax_cep.axhline(0, color='grey', lw=0.5, alpha=0.5)
    ax_cep.axvline(0, color='grey', lw=0.5, alpha=0.5)
    ax_cep.set_xlim(-lim, lim)
    ax_cep.set_ylim(-lim, lim)
    
    ax_cep.set_xlabel('East Error (m)', fontsize=11)
    ax_cep.set_ylabel('North Error (m)', fontsize=11)
    ax_cep.set_title('CEP — Position Error Density', fontsize=13, fontweight='bold', pad=8)
    ax_cep.legend(loc='upper right', fontsize=9)
    ax_cep.grid(True, alpha=0.3)
    
    # CEP stats text (right)
    ax_cep_stats = fig.add_subplot(gs[7, 1])
    ax_cep_stats.axis('off')
    
    cep_text = (
        f"━━━━  CEP Analysis  ━━━━\n\n"
        f"  Position samples:  {len(radial_err)}\n\n"
        f"  Circular Error Probable:\n"
        f"    CEP50:           {cep50:.1f} m\n"
        f"    CEP95:           {cep95:.1f} m\n"
        f"    CEP99:           {cep99:.1f} m\n\n"
        f"  RMS Error:         {rms_err:.1f} m\n"
        f"  Max Error:         {np.max(radial_err):.1f} m\n"
        f"  Mean Error:        {np.mean(radial_err):.1f} m\n\n"
        f"  East Error:\n"
        f"    Std dev:         {np.std(east_err):.1f} m\n"
        f"    Range:           {np.min(east_err):.1f} to {np.max(east_err):.1f} m\n\n"
        f"  North Error:\n"
        f"    Std dev:         {np.std(north_err):.1f} m\n"
        f"    Range:           {np.min(north_err):.1f} to {np.max(north_err):.1f} m\n\n"
        f"  Vertical (altitude):\n"
        f"    Std dev:         {np.std(valid_a):.1f} m\n"
        f"    Range:           {max(valid_a)-min(valid_a):.0f} m\n"
    )
    
    ax_cep_stats.text(0.05, 0.95, cep_text, transform=ax_cep_stats.transAxes,
                      fontsize=10, verticalalignment='top', fontfamily='monospace',
                      bbox=dict(boxstyle='round,pad=0.5', facecolor='#ecf0f1', alpha=0.8))

# ── Save ─────────────────────────────────────────────────────────────────────
outpath = '/home/englotk/working/noaa/ground/gnss_performance.pdf'
fig.savefig(outpath, bbox_inches='tight')
print(f'Saved to {outpath}')
plt.close()
