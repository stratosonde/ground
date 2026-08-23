#!/usr/bin/env python3
"""
GNSS Correlation Analysis
Pairwise scatter/correlation matrix between HDOP, satellites, altitude, TTF, SNR, etc.
Filtered to Jan 7-8, 2026
"""

import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from datetime import datetime, timezone
from scipy import stats as sp_stats

# ── Load & filter data ──────────────────────────────────────────────────────
with open('/home/englotk/working/noaa/ground/data/telemetry_data.json') as f:
    data = json.load(f)

for r in data:
    ts = r['timestamp']
    if ts.endswith('+00:00'):
        ts = ts.replace('+00:00', '+0000')
    r['dt'] = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f%z')

start = datetime(2026, 1, 7, tzinfo=timezone.utc)
end = datetime(2026, 1, 9, tzinfo=timezone.utc)
data = [r for r in data if start <= r['dt'] < end]
data = [r for r in data if r.get('altitude', 1) != 0.0]
data = [r for r in data if r.get('hdop', 0) < 25]

# ── Build feature table ─────────────────────────────────────────────────────
rows = []
for r in data:
    gd = r.get('gnss_detail', {}) or {}
    
    # Compute mean GPS SNR (excluding SNR=0 which means "tracked but no signal")
    gps_sats = [s['snr'] for s in gd.get('gps_satellites', []) if s.get('prn', 99) <= 32 and s['snr'] > 0]
    mean_snr = np.mean(gps_sats) if gps_sats else np.nan
    
    # Count sats with SNR > 20 (usable signal)
    strong_sats = sum(1 for s in gps_sats if s >= 20) if gps_sats else np.nan
    
    row = {
        'altitude': r.get('altitude'),
        'hdop': r.get('hdop'),
        'satellites': r.get('satellites'),
        'sats_used': gd.get('satellites_used'),
        'ttf': r.get('ttf_seconds') if r.get('ttf_seconds', 0) > 0 else np.nan,
        'gps_count': gd.get('gps_count'),
        'mean_snr': mean_snr,
        'strong_sats': strong_sats,
        'ground_speed': gd.get('ground_speed_kmh'),
        'vert_speed': gd.get('vertical_speed_ms'),
        'battery': r.get('battery_voltage'),
        'temperature': r.get('temperature'),
    }
    rows.append(row)

# Variables to correlate
var_names = [
    ('hdop', 'HDOP'),
    ('satellites', 'Sats in View'),
    ('sats_used', 'Sats Used'),
    ('altitude', 'Altitude (m)'),
    ('ttf', 'TTF (s)'),
    ('mean_snr', 'Mean GPS SNR'),
    ('strong_sats', 'Strong Sats\n(SNR≥20)'),
    ('temperature', 'Temperature (°C)'),
    ('battery', 'Battery (V)'),
]

n = len(var_names)

# ── Compute correlation matrix ──────────────────────────────────────────────
corr_matrix = np.full((n, n), np.nan)
pval_matrix = np.full((n, n), np.nan)

for i, (ki, _) in enumerate(var_names):
    for j, (kj, _) in enumerate(var_names):
        xi = np.array([r[ki] for r in rows], dtype=float)
        xj = np.array([r[kj] for r in rows], dtype=float)
        mask = ~(np.isnan(xi) | np.isnan(xj))
        if mask.sum() > 10:
            r_val, p_val = sp_stats.pearsonr(xi[mask], xj[mask])
            corr_matrix[i, j] = r_val
            pval_matrix[i, j] = p_val

# ═══════════════════════════════════════════════════════════════════════════════
# Figure 1: Correlation heatmap + scatter matrix
# ═══════════════════════════════════════════════════════════════════════════════
fig = plt.figure(figsize=(24, 26))
fig.suptitle('GNSS Correlation Analysis\nstrato3 · Jan 7–8, 2026',
             fontsize=18, fontweight='bold', y=0.995)

# Top section: correlation heatmap
gs_top = fig.add_gridspec(1, 1, left=0.08, right=0.92, top=0.96, bottom=0.62)
ax_hm = fig.add_subplot(gs_top[0, 0])

im = ax_hm.imshow(corr_matrix, cmap='RdBu_r', vmin=-1, vmax=1, aspect='auto')
cbar = plt.colorbar(im, ax=ax_hm, shrink=0.8, pad=0.02)
cbar.set_label('Pearson r', fontsize=12)

labels = [name for _, name in var_names]
ax_hm.set_xticks(range(n))
ax_hm.set_yticks(range(n))
ax_hm.set_xticklabels(labels, fontsize=10, rotation=45, ha='right')
ax_hm.set_yticklabels(labels, fontsize=10)

# Annotate cells with r values
for i in range(n):
    for j in range(n):
        r_val = corr_matrix[i, j]
        p_val = pval_matrix[i, j]
        if not np.isnan(r_val):
            sig = '***' if p_val < 0.001 else '**' if p_val < 0.01 else '*' if p_val < 0.05 else ''
            color = 'white' if abs(r_val) > 0.5 else 'black'
            ax_hm.text(j, i, f'{r_val:.2f}{sig}', ha='center', va='center',
                       fontsize=9, fontweight='bold', color=color)

ax_hm.set_title('Pearson Correlation Matrix (* p<0.05, ** p<0.01, *** p<0.001)',
                 fontsize=14, fontweight='bold', pad=12)

# ═══════════════════════════════════════════════════════════════════════════════
# Bottom section: Key scatter plots (3 rows x 3 cols)
# ═══════════════════════════════════════════════════════════════════════════════
gs_bot = fig.add_gridspec(3, 3, left=0.08, right=0.95, top=0.57, bottom=0.02,
                          hspace=0.4, wspace=0.35)

scatter_pairs = [
    ('satellites', 'hdop', 'Sats in View', 'HDOP'),
    ('sats_used', 'hdop', 'Sats Used in Fix', 'HDOP'),
    ('mean_snr', 'hdop', 'Mean GPS SNR (dB-Hz)', 'HDOP'),
    ('altitude', 'hdop', 'Altitude (m)', 'HDOP'),
    ('ttf', 'hdop', 'TTF (s)', 'HDOP'),
    ('temperature', 'hdop', 'Temperature (°C)', 'HDOP'),
    ('satellites', 'ttf', 'Sats in View', 'TTF (s)'),
    ('mean_snr', 'ttf', 'Mean GPS SNR (dB-Hz)', 'TTF (s)'),
    ('temperature', 'satellites', 'Temperature (°C)', 'Sats in View'),
]

for idx, (kx, ky, lx, ly) in enumerate(scatter_pairs):
    row, col = divmod(idx, 3)
    ax = fig.add_subplot(gs_bot[row, col])
    
    x = np.array([r[kx] for r in rows], dtype=float)
    y = np.array([r[ky] for r in rows], dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    
    if mask.sum() > 5:
        xm, ym = x[mask], y[mask]
        
        # Scatter
        ax.scatter(xm, ym, c='#3498db', alpha=0.35, s=18, edgecolors='none')
        
        # Regression line
        slope, intercept, r_val, p_val, se = sp_stats.linregress(xm, ym)
        x_line = np.linspace(np.min(xm), np.max(xm), 50)
        ax.plot(x_line, slope * x_line + intercept, 'r-', lw=2, alpha=0.7)
        
        # Annotate r value
        sig = '***' if p_val < 0.001 else '**' if p_val < 0.01 else '*' if p_val < 0.05 else ' ns'
        ax.text(0.05, 0.95, f'r = {r_val:.3f}{sig}\nn = {mask.sum()}',
                transform=ax.transAxes, fontsize=10, verticalalignment='top',
                fontfamily='monospace',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='wheat', alpha=0.7))
        
        # Cap HDOP y-axis at 7
        if ky == 'hdop':
            ax.set_ylim(0, 7)
    
    ax.set_xlabel(lx, fontsize=10)
    ax.set_ylabel(ly, fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=9)

# ── Save ─────────────────────────────────────────────────────────────────────
outpath = '/home/englotk/working/noaa/ground/gnss_correlations.pdf'
fig.savefig(outpath, bbox_inches='tight')
print(f'Saved to {outpath}')
plt.close()
