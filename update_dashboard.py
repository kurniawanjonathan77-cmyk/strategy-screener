with open('src/dashboard/generate.py', 'r') as f:
    content = f.read()

# Find the footer section
footer_marker = 'html += f"""\n        <!-- Footer -->'
idx = content.index(footer_marker)

futures_section = '''
    # Futures Summary Section
    if config.get("output", {}).get("dashboard", {}).get("show_futures", False):
        futures_signals = [s for s in signals if s.get("metadata", {}).get("futures")]
        if futures_signals:
            total_signals = len(futures_signals)
            avg_leverage = sum(s.get("metadata", {}).get("futures", {}).get("leverage", {}).get("suggested", 1) for s in futures_signals) / total_signals
            avg_liq_buffer = sum(s.get("metadata", {}).get("futures", {}).get("liquidation", {}).get("buffer_from_sl_pct", 0) for s in futures_signals) / total_signals
            avg_roe_tp = sum(s.get("metadata", {}).get("futures", {}).get("returns", {}).get("roe_tp_pct", 0) for s in futures_signals) / total_signals
            avg_roe_sl = sum(s.get("metadata", {}).get("futures", {}).get("returns", {}).get("roe_sl_pct", 0) for s in futures_signals) / total_signals
            avg_funding = sum(s.get("metadata", {}).get("futures", {}).get("funding", {}).get("cost_to_tp_pct", 0) for s in futures_signals) / total_signals
            high_risk = sum(1 for s in futures_signals if s.get("metadata", {}).get("futures", {}).get("risk", {}).get("risk_level") == "HIGH")
            med_risk = sum(1 for s in futures_signals if s.get("metadata", {}).get("futures", {}).get("risk", {}).get("risk_level") == "MEDIUM")
            low_risk = sum(1 for s in futures_signals if s.get("metadata", {}).get("futures", {}).get("risk", {}).get("risk_level") == "LOW")
            
            # Leverage distribution
            lev_dist = {}
            for s in futures_signals:
                lev = s.get("metadata", {}).get("futures", {}).get("leverage", {}).get("suggested", 1)
                lev_dist[lev] = lev_dist.get(lev, 0) + 1
            
            html += f"""
        <div class="section">
            <div class="section-header">
                <h2 class="section-title">Futures Analysis Summary</h2>
            </div>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Signals with Futures</div>
                    <div class="stat-value">{total_signals}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Avg Suggested Leverage</div>
                    <div class="stat-value">{avg_leverage:.1f}x</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Avg Liq Buffer</div>
                    <div class="stat-value">{avg_liq_buffer:.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Avg ROE at TP</div>
                    <div class="stat-value">{avg_roe_tp:+.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Avg ROE at SL</div>
                    <div class="stat-value">{avg_roe_sl:+.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Avg Funding Cost</div>
                    <div class="stat-value">{avg_funding:+.3f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Risk Distribution</div>
                    <div class="stat-value" style="font-size: 1rem;">
                        <span style="color:#f85149">HIGH: {high_risk}</span> | 
                        <span style="color:#d29922">MED: {med_risk}</span> | 
                        <span style="color:#3fb950">LOW: {low_risk}</span>
                    </div>
                </div>
            </div>
            
            <div style="margin-top: 20px;">
                <h3 style="margin-bottom: 10px; color: #8b949e;">Leverage Distribution</h3>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
"""
            for lev in sorted(lev_dist.keys()):
                count = lev_dist[lev]
                pct = count / total_signals * 100
                html += f'<div class="badge" style="background:#58a6ff; padding:8px 12px;">{lev}x: {count} ({pct:.0f}%)</div>'
            
            html += """
                </div>
            </div>
        </div>
"""
    
    html += f"""
        <!-- Footer -->
"""

new_content = content[:idx] + futures_section + content[idx:]
with open('src/dashboard/generate.py', 'w') as f:
    f.write(new_content)
print('Done')