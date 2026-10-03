"""Dashboard Generator - Creates static HTML + JSON for GitHub Pages"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from src.strategies.base import Signal


def generate_dashboard(signals: List[Signal], backtests: List[Dict], config: dict, output_dir: str = "docs"):
    """Generate dashboard HTML and JSON files"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Prepare data
    signals_data = [s.to_dict() for s in signals]
    backtests_data = []
    
    for bt in backtests:
        backtests_data.append({
            "strategy": bt["strategy"],
            "symbol": bt["symbol"],
            "trades": bt["overall"]["total_trades"],
            "win_rate": bt["overall"]["win_rate"],
            "expectancy": bt["overall"]["expectancy"],
            "sharpe": bt["overall"]["sharpe_ratio"],
            "max_dd": bt["overall"]["max_drawdown"],
            "profit_factor": bt["overall"]["profit_factor"],
            "total_return": bt["overall"]["total_return"]
        })
    
    # Strategy summary
    strategy_summary = {}
    for bt in backtests:
        key = bt["strategy"]
        if key not in strategy_summary:
            strategy_summary[key] = {"count": 0, "avg_wr": 0, "avg_exp": 0, "avg_sharpe": 0, "avg_dd": 0, "avg_pf": 0}
        s = strategy_summary[key]
        s["count"] += 1
        s["avg_wr"] += bt["overall"]["win_rate"]
        s["avg_exp"] += bt["overall"]["expectancy"]
        s["avg_sharpe"] += bt["overall"]["sharpe_ratio"]
        s["avg_dd"] += bt["overall"]["max_drawdown"]
        s["avg_pf"] += bt["overall"]["profit_factor"]
    
    for s in strategy_summary.values():
        if s["count"] > 0:
            s["avg_wr"] /= s["count"]
            s["avg_exp"] /= s["count"]
            s["avg_sharpe"] /= s["count"]
            s["avg_dd"] /= s["count"]
            s["avg_pf"] /= s["count"]
    
    # Save JSON files
    (output_path / "signals.json").write_text(json.dumps({
        "timestamp": datetime.utcnow().isoformat(),
        "signals": signals_data
    }, indent=2))
    
    (output_path / "performance.json").write_text(json.dumps({
        "timestamp": datetime.utcnow().isoformat(),
        "backtests": backtests_data,
        "strategy_summary": strategy_summary
    }, indent=2))
    
    # Generate HTML
    html = generate_html(signals_data, backtests_data, strategy_summary, config)
    (output_path / "index.html").write_text(html)
    
    print(f"Dashboard generated in {output_path}")


def generate_html(signals: List[Dict], backtests: List[Dict], strategy_summary: Dict, config: dict) -> str:
    """Generate HTML dashboard"""
    
    # Group signals by strategy
    signals_by_strategy = {}
    for s in signals:
        strat = s["strategy"]
        if strat not in signals_by_strategy:
            signals_by_strategy[strat] = []
        signals_by_strategy[strat].append(s)
    
    # Sort backtests by expectancy
    backtests_sorted = sorted(backtests, key=lambda x: x["expectancy"], reverse=True)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{config['output']['dashboard']['title']}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: 'Segoe UI', system-ui, sans-serif; 
            background: #0d1117; color: #e6edf3;
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        header {{ 
            display: flex; justify-content: space-between; align-items: center;
            padding: 20px 0; border-bottom: 1px solid #30363d;
            margin-bottom: 30px;
        }}
        h1 {{ font-size: 1.8rem; font-weight: 600; }}
        .last-update {{ color: #8b949e; font-size: 0.9rem; }}
        .stats-grid {{ 
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px; margin-bottom: 30px;
        }}
        .stat-card {{
            background: #161b22; border: 1px solid #30363d;
            border-radius: 8px; padding: 20px;
        }}
        .stat-label {{ color: #8b949e; font-size: 0.85rem; text-transform: uppercase; }}
        .stat-value {{ font-size: 1.5rem; font-weight: 600; margin-top: 4px; }}
        .stat-value.positive {{ color: #3fb950; }}
        .stat-value.negative {{ color: #f85149; }}
        
        .section {{ margin-bottom: 40px; }}
        .section-header {{ 
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid #30363d;
        }}
        .section-title {{ font-size: 1.2rem; font-weight: 600; }}
        
        table {{ width: 100%; border-collapse: collapse; background: #161b22; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #30363d; }}
        th {{ background: #21262d; font-weight: 600; color: #8b949e; font-size: 0.8rem; text-transform: uppercase; }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover {{ background: #21262d; }}
        
        .badge {{ 
            display: inline-block; padding: 2px 8px; border-radius: 4px; 
            font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
        }}
        .badge-long {{ background: #1f6feb; color: white; }}
        .badge-short {{ background: #f85149; color: white; }}
        .badge-strategy {{ background: #238636; color: white; }}
        
        .confidence-bar {{ 
            width: 80px; height: 6px; background: #30363d; border-radius: 3px; overflow: hidden;
        }}
        .confidence-fill {{ height: 100%; border-radius: 3px; transition: width 0.3s; }}
        
        .rr-badge {{ font-weight: 600; }}
        .rr-high {{ color: #3fb950; }}
        .rr-med {{ color: #d29922; }}
        .rr-low {{ color: #f85149; }}
        
        .strategy-tabs {{ display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }}
        .tab {{ 
            padding: 8px 16px; background: #161b22; border: 1px solid #30363d;
            border-radius: 6px; cursor: pointer; font-size: 0.85rem;
            transition: all 0.2s;
        }}
        .tab.active {{ background: #1f6feb; border-color: #1f6feb; color: white; }}
        .tab:hover:not(.active) {{ background: #21262d; }}
        
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        
        .empty-state {{ text-align: center; padding: 60px 20px; color: #8b949e; }}
        
        @media (max-width: 768px) {{
            table {{ font-size: 0.8rem; }}
            th, td {{ padding: 8px 10px; }}
            .container {{ padding: 10px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Strategy Screener</h1>
            <div class="last-update">Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>
        </header>
        
        <!-- Stats Cards -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Active Signals</div>
                <div class="stat-value">{len(signals)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Backtested Strategies</div>
                <div class="stat-value">{len(backtests)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Symbols Covered</div>
                <div class="stat-value">{len(set(b['symbol'] for b in backtests))}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Best Expectancy</div>
                <div class="stat-value positive">{max([b['expectancy'] for b in backtests], default=0):.4f}</div>
            </div>
        </div>
        
        <!-- Strategy Performance Summary -->
        <div class="section">
            <div class="section-header">
                <h2 class="section-title">📈 Strategy Performance (Walk-Forward Backtest)</h2>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Strategy</th>
                        <th>Symbols</th>
                        <th>Avg Win Rate</th>
                        <th>Avg Expectancy</th>
                        <th>Avg Sharpe</th>
                        <th>Avg Max DD</th>
                        <th>Avg Profit Factor</th>
                    </tr>
                </thead>
                <tbody>
"""
    
    for strat, stats in sorted(strategy_summary.items(), key=lambda x: x[1]["avg_exp"], reverse=True):
        html += f"""
                    <tr>
                        <td><span class="badge badge-strategy">{strat}</span></td>
                        <td>{stats['count']}</td>
                        <td>{stats['avg_wr']:.1%}</td>
                        <td class="{'positive' if stats['avg_exp'] > 0 else 'negative'}">{stats['avg_exp']:.4f}</td>
                        <td>{stats['avg_sharpe']:.2f}</td>
                        <td class="negative">{stats['avg_dd']:.1%}</td>
                        <td>{backtests_sorted[0]['profit_factor'] if backtests_sorted else 0:.2f}</td>
                    </tr>
"""
    
    html += """
                </tbody>
            </table>
        </div>
        
        <!-- Top Signals by Strategy -->
        <div class="section">
            <div class="section-header">
                <h2 class="section-title">🎯 Current Signals</h2>
            </div>
            <div class="strategy-tabs">
"""
    
    for strat in signals_by_strategy.keys():
        active = 'active' if strat == list(signals_by_strategy.keys())[0] else ''
        html += f'<button class="tab {active}" onclick="showTab(\'{strat}\')">{strat.replace("_", " ").title()}</button>'
    
    html += """
            </div>
"""
    
    for strat, sigs in signals_by_strategy.items():
        active = 'active' if strat == list(signals_by_strategy.keys())[0] else ''
        html += f'<div class="tab-content {active}" id="tab-{strat}">'
        html += """
                <table>
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Direction</th>
                            <th>Entry</th>
                            <th>Stop Loss</th>
                            <th>Take Profit</th>
                            <th>R:R</th>
                            <th>Confidence</th>
                            <th>Backtest WR</th>
                            <th>Backtest Exp</th>
                            <th>Leverage</th>
                            <th>Liq Buffer</th>
                            <th>ROE TP/SL</th>
                            <th>Funding Cost</th>
                            <th>Risk Level</th>
                            <th>Details</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        
        for s in sigs:
            direction_class = "badge-long" if s["direction"] == "long" else "badge-short"
            rr = s["risk_reward"]
            rr_class = "rr-high" if rr >= 2 else "rr-med" if rr >= 1.5 else "rr-low"
            conf = s["confidence"]
            conf_color = "#3fb950" if conf >= 0.7 else "#d29922" if conf >= 0.55 else "#f85149"
            
            bt = s.get("metadata", {}).get("backtest", {})
            bt_wr = bt.get("win_rate", 0)
            bt_exp = bt.get("expectancy", 0)
            
            # Futures data
            futures = s.get("metadata", {}).get("futures", {})
            leverage = futures.get("leverage", {}).get("suggested", 1)
            liq_buffer = futures.get("liquidation", {}).get("buffer_from_sl_pct", 0)
            returns = futures.get("returns", {})
            roe_tp = returns.get("roe_tp_pct", 0)
            roe_sl = returns.get("roe_sl_pct", 0)
            funding = futures.get("funding", {})
            funding_cost = funding.get("cost_to_tp_pct", 0)
            risk = futures.get("risk", {})
            risk_level = risk.get("risk_level", "LOW")
            risk_color = "#f85149" if risk_level == "HIGH" else "#d29922" if risk_level == "MEDIUM" else "#3fb950"
            
            reasons = s.get("metadata", {}).get("reasons", [])
            details = "; ".join(reasons[:3]) if reasons else "—"
            
            html += f"""
                        <tr>
                            <td><strong>{s['symbol']}</strong></td>
                            <td><span class="badge {direction_class}">{s['direction']}</span></td>
                            <td>${s['entry_price']:.6f}</td>
                            <td>${s['stop_loss']:.6f}</td>
                            <td>${s['take_profit']:.6f}</td>
                            <td class="rr-badge {rr_class}">{rr:.1f}:1</td>
                            <td>
                                <div class="confidence-bar">
                                    <div class="confidence-fill" style="width: {conf*100}%; background: {conf_color};"></div>
                                </div>
                                <span style="font-size: 0.75rem;">{conf:.0%}</span>
                            </td>
                            <td>{bt_wr:.1%}</td>
                            <td class="{'positive' if bt_exp > 0 else 'negative'}">{bt_exp:.4f}</td>
                            <td><span class="badge" style="background:#58a6ff;">{s.get('metadata',{}).get('futures',{}).get('leverage',{}).get('suggested',1)}x</span></td>
                            <td style="color:{'#f85149' if liq_buffer < 5 else '#d29922' if liq_buffer < 10 else '#3fb950'}">{liq_buffer:.1f}%</td>
                            <td style="font-size:0.75rem;">{roe_tp:+.1f}% / {roe_sl:+.1f}%</td>
                            <td style="font-size:0.75rem;color:#8b949e">{funding_cost:+.3f}%</td>
                            <td><span class="badge" style="background:{risk_color}">{risk_level}</span></td>
                            <td style="font-size: 0.75rem; color: #8b949e; max-width: 200px;">{details}</td>
                        </tr>
"""
        
        html += """
                    </tbody>
                </table>
            </div>
"""
    
    # Polymarket signals if any
    pm_signals = [s for s in signals if s["strategy"] == "polymarket_arb"]
    if pm_signals:
        html += """
        <div class="section">
            <div class="section-header">
                <h2 class="section-title">⚡ Polymarket Mispricing</h2>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Market</th>
                        <th>Outcomes</th>
                        <th>Prices</th>
                        <th>Edge</th>
                        <th>Direction</th>
                        <th>Volume 24h</th>
                        <th>Liquidity</th>
                    </tr>
                </thead>
                <tbody>
"""
        for s in pm_signals:
            m = s["metadata"]
            html += f"""
                    <tr>
                        <td style="max-width: 300px;">{m.get('market_question', 'N/A')[:80]}</td>
                        <td>{', '.join(m.get('outcomes', []))}</td>
                        <td>{m.get('prices', {})}</td>
                        <td class="positive">{m.get('edge_pct', 0):.2f}%</td>
                        <td><span class="badge badge-long">{m.get('direction', '').replace('_', ' ')}</span></td>
                        <td>${m.get('volume_24h', 0):,.0f}</td>
                        <td>${m.get('liquidity', 0):,.0f}</td>
                    </tr>
"""
        html += """
                </tbody>
            </table>
        </div>
"""
    
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
        <div style="text-align: center; padding: 40px 0; color: #8b949e; border-top: 1px solid #30363d;">
            <p>Strategy Screener | Data: CoinGecko + Polymarket Testnet | 
            <a href="https://github.com" style="color: #58a6ff;">GitHub</a> | 
            Updated every 15 min via GitHub Actions</p>
        </div>
    </div>
    
    <script>
        function showTab(tabId) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('tab-' + tabId).classList.add('active');
        }}
        
        // Auto-refresh every 15 minutes
        setTimeout(() => location.reload(), 15 * 60 * 1000);
    </script>
</body>
</html>
"""
    return html