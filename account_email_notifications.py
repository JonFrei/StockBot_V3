"""
Email Notification System - ROBUST TWO-TIER APPROACH

Sends:
1. Execution Summary (ALWAYS SENT) - timestamp, status, errors
2. Detailed Trading Summary (BEST EFFORT) - positions, trades, performance
3. Crash notification emails (when bot encounters fatal errors)

Only sends emails during live trading (not backtesting)

Key Features:
- Guarantees daily email even if data collection fails
- Tracks execution start/end times
- Captures and reports all errors with full tracebacks
- Separates execution status from trading details
- Falls back to console logging when email fails
- Uses Resend API (Railway-compatible, works everywhere)

Email Configuration:
==========================================
Set these environment variables in Railway:

Required:
- RESEND_API_KEY: Get from https://resend.com/api-keys
- EMAIL_SENDER: Your verified sender email
- EMAIL_RECIPIENT: Where to send reports

Setup:
1. Sign up at https://resend.com (free tier: 100 emails/day)
2. Add and verify your domain OR use onboarding@resend.dev
3. Create API key
4. Add RESEND_API_KEY to Railway environment variables

Example:
RESEND_API_KEY=re_123456789
EMAIL_SENDER=bot@yourdomain.com
EMAIL_RECIPIENT=you@email.com
==========================================
"""

import os
from datetime import datetime
from config import Config
import traceback


# =============================================================================
# EXECUTION TRACKING
# =============================================================================

class ExecutionTracker:
    """Tracks bot execution for email reporting"""

    def __init__(self):
        self.start_time = datetime.now()
        self.end_time = None
        self.errors = []
        self.warnings = []
        self.actions = {
            'exits': 0,
            'entries': 0,
            'rotation': False,
            'drawdown_protection': False
        }
        self.status = 'RUNNING'

    def add_error(self, context, error, error_traceback=None):
        """Record an error with full context"""
        self.errors.append({
            'context': context,
            'error': str(error),
            'traceback': error_traceback or traceback.format_exc(),
            'timestamp': datetime.now()
        })

    def add_warning(self, message):
        """Record a warning"""
        self.warnings.append({
            'message': message,
            'timestamp': datetime.now()
        })

    def record_action(self, action_type, count=1):
        """Record a trading action"""
        if action_type in self.actions:
            if isinstance(self.actions[action_type], int):
                self.actions[action_type] += count
            else:
                self.actions[action_type] = True

    def complete(self, status='SUCCESS'):
        """Mark execution as complete"""
        self.end_time = datetime.now()
        self.status = status

    def get_duration(self):
        """Get execution duration"""
        end = self.end_time or datetime.now()
        duration = end - self.start_time
        return duration.total_seconds()


# =============================================================================
# EMAIL SENDING
# =============================================================================

def send_email(subject, body_html, body_text=None):
    """
    Send email with HTML content using Resend API

    Falls back to console logging if email fails (e.g., no API key configured)

    Args:
        subject: Email subject line
        body_html: HTML content
        body_text: Plain text fallback (optional)

    Returns:
        bool: True if sent successfully, False otherwise
    """
    # Skip if in backtesting mode
    if Config.BACKTESTING:
        return False

    # Check if email is configured
    if not all([Config.EMAIL_SENDER, Config.EMAIL_RECIPIENT]):
        print("[EMAIL] Email not configured - logging to console instead")
        _log_email_to_console(subject, body_html)
        return False

    # Get Resend API key
    resend_api_key = os.getenv('RESEND_API_KEY')
    if not resend_api_key:
        print("[EMAIL] RESEND_API_KEY not found - logging to console instead")
        _log_email_to_console(subject, body_html)
        return False

    try:
        import requests

        # Resend API endpoint
        url = "https://api.resend.com/emails"

        # Prepare payload
        payload = {
            "from": Config.EMAIL_SENDER,
            "to": [Config.EMAIL_RECIPIENT],
            "subject": subject,
            "html": body_html
        }

        # Add text version if provided
        if body_text:
            payload["text"] = body_text

        # Send request
        headers = {
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code in [200, 201]:
            print(f"[EMAIL] ✅ Sent via Resend: {subject}")
            return True
        else:
            print(f"[EMAIL] ❌ Resend API error: {response.status_code} - {response.text}")
            _log_email_to_console(subject, body_html)
            return False

    except Exception as e:
        print(f"[EMAIL] ❌ Failed to send email: {e}")
        print(f"[EMAIL] 📝 Logging email content to console instead...")
        _log_email_to_console(subject, body_html)
        return False


def _log_email_to_console(subject, body_html):
    """
    Log email content to console when email sending fails

    Useful for Railway deployments where Resend API key not configured
    """
    print(f"\n{'=' * 80}")
    print(f"📧 EMAIL CONTENT (Console Log)")
    print(f"{'=' * 80}")
    print(f"Subject: {subject}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p EST')}")
    print(f"{'=' * 80}")

    # Strip HTML tags for console readability
    try:
        import re
        # Remove HTML tags
        text = re.sub('<[^<]+?>', '', body_html)
        # Remove multiple newlines
        text = re.sub(r'\n\s*\n', '\n', text)
        # Decode HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')

        print(text)
    except:
        # Fallback: just print raw HTML
        print(body_html)

    print(f"{'=' * 80}\n")
    print(f"[EMAIL] ℹ️  To enable email delivery:")
    print(f"[EMAIL]    1. Sign up at https://resend.com (free 100 emails/day)")
    print(f"[EMAIL]    2. Get API key from dashboard")
    print(f"[EMAIL]    3. Add RESEND_API_KEY to Railway environment variables")
    print(f"{'=' * 80}\n")


# =============================================================================
# TWO-TIER EMAIL SYSTEM
# =============================================================================

def send_daily_summary_email(strategy, current_date, execution_tracker=None):
    """
    Send comprehensive daily email with execution summary and trading details

    ALWAYS SENDS EMAIL - even if data collection fails

    Args:
        strategy: Lumibot Strategy instance
        current_date: Current datetime object
        execution_tracker: ExecutionTracker instance (optional)
    """
    # Skip if backtesting
    if Config.BACKTESTING:
        return

    print("\n[EMAIL] Preparing daily summary email...")

    # Create tracker if not provided
    if execution_tracker is None:
        execution_tracker = ExecutionTracker()
        execution_tracker.complete('SUCCESS')

    try:
        # Build email in two sections
        html_body = generate_execution_summary_html(execution_tracker, current_date)

        # Try to append detailed summary (best effort)
        try:
            detailed_html = generate_detailed_summary_html(strategy, current_date)
            html_body += detailed_html
        except Exception as e:
            error_html = generate_error_section_html(
                "Detailed Trading Summary",
                str(e),
                traceback.format_exc()
            )
            html_body += error_html

        # Determine subject based on status
        if execution_tracker.status == 'SUCCESS' and len(execution_tracker.errors) == 0:
            subject = f"✅ Trading Bot Report - {current_date.strftime('%Y-%m-%d')}"
        elif execution_tracker.status == 'SUCCESS' and len(execution_tracker.errors) > 0:
            subject = f"⚠️ Trading Bot Report (With Errors) - {current_date.strftime('%Y-%m-%d')}"
        else:
            subject = f"❌ Trading Bot Report (Failed) - {current_date.strftime('%Y-%m-%d')}"

        send_email(subject, html_body)

    except Exception as e:
        # Last resort - send minimal email about email failure
        print(f"[EMAIL] Critical error generating email: {e}")
        try:
            minimal_html = f"""
            <html>
            <body>
                <h2>🚨 Email Generation Failed</h2>
                <p><strong>Date:</strong> {current_date.strftime('%Y-%m-%d %I:%M:%S %p')}</p>
                <p><strong>Error:</strong> {str(e)}</p>
                <pre>{traceback.format_exc()}</pre>
            </body>
            </html>
            """
            send_email(f"🚨 Email System Error - {current_date.strftime('%Y-%m-%d')}", minimal_html)
        except:
            print(f"[EMAIL] Failed to send even minimal error email")


# =============================================================================
# HTML GENERATION - EXECUTION SUMMARY (ALWAYS INCLUDED)
# =============================================================================

def generate_execution_summary_html(execution_tracker, current_date):
    """
    Generate HTML for execution summary section

    This section ALWAYS renders successfully with available data

    Returns:
        str: HTML content
    """
    duration = execution_tracker.get_duration()
    duration_str = f"{int(duration // 60)}m {int(duration % 60)}s"

    # Status styling
    if execution_tracker.status == 'SUCCESS' and len(execution_tracker.errors) == 0:
        status_color = '#27ae60'
        status_icon = '✅'
    elif execution_tracker.status == 'SUCCESS' and len(execution_tracker.errors) > 0:
        status_color = '#f39c12'
        status_icon = '⚠️'
    else:
        status_color = '#e74c3c'
        status_icon = '❌'

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            h3 {{ color: #34495e; margin-top: 20px; }}
            .execution-box {{ background-color: #ecf0f1; padding: 20px; border-radius: 5px; margin: 20px 0; }}
            .status-box {{ padding: 15px; border-radius: 5px; margin: 10px 0; border-left: 5px solid {status_color}; }}
            .error-box {{ background-color: #fadbd8; padding: 15px; border-left: 5px solid #e74c3c; margin: 10px 0; }}
            .warning-box {{ background-color: #fcf3cf; padding: 15px; border-left: 5px solid #f39c12; margin: 10px 0; }}
            .success-box {{ background-color: #d5f4e6; padding: 15px; border-left: 5px solid #27ae60; margin: 10px 0; }}
            .traceback {{ background-color: #f4f4f4; padding: 10px; border: 1px solid #ddd; font-family: monospace; 
                         font-size: 0.85em; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; }}
            table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
            th {{ background-color: #3498db; color: white; padding: 10px; text-align: left; }}
            td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
            .timestamp {{ color: #7f8c8d; font-size: 0.9em; }}
            .section-divider {{ border-top: 3px solid #3498db; margin: 30px 0; }}
        </style>
    </head>
    <body>
        <h2>🤖 Trading Bot Execution Report</h2>
        <p class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p EST')}</p>

        <div class="execution-box">
            <h3>⏱️ Execution Summary</h3>
            <table>
                <tr>
                    <td><strong>Start Time:</strong></td>
                    <td>{execution_tracker.start_time.strftime('%Y-%m-%d %I:%M:%S %p EST')}</td>
                </tr>
                <tr>
                    <td><strong>End Time:</strong></td>
                    <td>{execution_tracker.end_time.strftime('%Y-%m-%d %I:%M:%S %p EST') if execution_tracker.end_time else 'In Progress'}</td>
                </tr>
                <tr>
                    <td><strong>Duration:</strong></td>
                    <td>{duration_str}</td>
                </tr>
                <tr>
                    <td><strong>Status:</strong></td>
                    <td style="color: {status_color}; font-weight: bold;">{status_icon} {execution_tracker.status}</td>
                </tr>
            </table>
        </div>

        <div class="status-box">
            <h3>📊 Actions Taken</h3>
            <table>
                <tr>
                    <td><strong>Position Entries:</strong></td>
                    <td>{execution_tracker.actions['entries']}</td>
                </tr>
                <tr>
                    <td><strong>Position Exits:</strong></td>
                    <td>{execution_tracker.actions['exits']}</td>
                </tr>
                <tr>
                    <td><strong>Stock Rotation:</strong></td>
                    <td>{'Yes' if execution_tracker.actions['rotation'] else 'No'}</td>
                </tr>
                <tr>
                    <td><strong>Drawdown Protection:</strong></td>
                    <td>{'ACTIVATED' if execution_tracker.actions['drawdown_protection'] else 'Not Triggered'}</td>
                </tr>
            </table>
        </div>
    """

    # Add errors section if any
    if execution_tracker.errors:
        html += f"""
        <div class="error-box">
            <h3>❌ Errors Encountered ({len(execution_tracker.errors)})</h3>
        """

        for i, error in enumerate(execution_tracker.errors, 1):
            html += f"""
            <div style="margin-bottom: 20px;">
                <p><strong>Error {i}: {error['context']}</strong></p>
                <p class="timestamp">{error['timestamp'].strftime('%I:%M:%S %p')}</p>
                <p><strong>Message:</strong> {error['error']}</p>
                <div class="traceback">
                    <strong>Full Traceback:</strong><br>
{error['traceback']}
                </div>
            </div>
            """

        html += "</div>"
    else:
        html += """
        <div class="success-box">
            <h3>✅ No Errors</h3>
            <p>Bot completed execution without errors.</p>
        </div>
        """

    # Add warnings section if any
    if execution_tracker.warnings:
        html += f"""
        <div class="warning-box">
            <h3>⚠️ Warnings ({len(execution_tracker.warnings)})</h3>
            <ul>
        """

        for warning in execution_tracker.warnings:
            html += f"""
                <li>
                    <strong>{warning['timestamp'].strftime('%I:%M:%S %p')}:</strong> {warning['message']}
                </li>
            """

        html += """
            </ul>
        </div>
        """

    # Add section divider
    html += '<div class="section-divider"></div>'

    return html


# =============================================================================
# HTML GENERATION - DETAILED SUMMARY (BEST EFFORT)
# =============================================================================

def generate_detailed_summary_html(strategy, current_date):
    """
    Generate HTML for detailed trading summary

    Uses safe data collection with error handling for each section

    Returns:
        str: HTML content
    """
    html = f"""
        <h2>📊 Detailed Trading Summary - {current_date.strftime('%B %d, %Y')}</h2>
    """

    # Portfolio Overview (safe)
    portfolio_html = safe_generate_portfolio_section(strategy)
    html += portfolio_html

    # Active Positions (safe)
    positions_html = safe_generate_positions_section(strategy)
    html += positions_html

    # Today's Closed Trades (safe)
    trades_html = safe_generate_trades_section(strategy, current_date)
    html += trades_html

    # Stock Rotation (safe)
    rotation_html = safe_generate_rotation_section(strategy)
    html += rotation_html

    # Overall Performance (safe)
    performance_html = safe_generate_performance_section(strategy)
    html += performance_html

    # Top Performers (safe)
    top_performers_html = safe_generate_top_performers_section(strategy)
    html += top_performers_html

    # Footer
    html += f"""
        <hr>
        <p style="color: #7f8c8d; font-size: 0.9em;">
            <em>Generated by SwingTradeStrategy Bot</em><br>
            <em>Report Timestamp: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p EST')}</em>
        </p>
    </body>
    </html>
    """

    return html


def safe_generate_portfolio_section(strategy):
    """Safely generate portfolio section with error handling"""
    try:
        cash = strategy.get_cash()
        portfolio_value = strategy.portfolio_value
        invested = portfolio_value - cash

        return f"""
        <div style="background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin: 10px 0;">
            <h3>💰 Portfolio Status</h3>
            <table>
                <tr><td><strong>Total Value:</strong></td><td>${portfolio_value:,.2f}</td></tr>
                <tr><td><strong>Cash:</strong></td><td>${cash:,.2f}</td></tr>
                <tr><td><strong>Invested:</strong></td><td>${invested:,.2f}</td></tr>
            </table>
        </div>
        """
    except Exception as e:
        return generate_error_section_html("Portfolio Status", str(e), traceback.format_exc())


def safe_generate_positions_section(strategy):
    """Safely generate positions section with error handling"""
    try:
        positions = strategy.get_positions()

        html = f"""
        <h3>📈 Active Positions ({len(positions)})</h3>
        """

        if positions:
            html += """
            <table>
                <tr>
                    <th>Ticker</th>
                    <th>Quantity</th>
                    <th>Entry</th>
                    <th>Current</th>
                    <th>P&L</th>
                    <th>%</th>
                    <th>Award</th>
                </tr>
            """

            total_unrealized = 0

            for position in positions:
                try:
                    ticker = position.symbol
                    qty = int(position.quantity)
                    entry_price = float(getattr(position, 'avg_entry_price', None) or
                                        getattr(position, 'avg_fill_price', 0))

                    current_price = strategy.get_last_price(ticker)
                    pnl_dollars = (current_price - entry_price) * qty
                    pnl_pct = ((current_price - entry_price) / entry_price * 100)
                    total_unrealized += pnl_dollars

                    # Get award from stock rotator
                    award = strategy.stock_rotator.get_award(ticker)
                    award_emoji = {
                        'premium': '🥇',
                        'standard': '🥈',
                        'trial': '🔬',
                        'none': '⚪',
                        'frozen': '❄️'
                    }.get(award, '❓')

                    pnl_class = 'positive' if pnl_dollars > 0 else 'negative'

                    html += f"""
                    <tr>
                        <td><strong>{ticker}</strong></td>
                        <td>{qty:,}</td>
                        <td>${entry_price:.2f}</td>
                        <td>${current_price:.2f}</td>
                        <td style="color: {'#27ae60' if pnl_dollars > 0 else '#e74c3c'}; font-weight: bold;">${pnl_dollars:+,.2f}</td>
                        <td style="color: {'#27ae60' if pnl_pct > 0 else '#e74c3c'}; font-weight: bold;">{pnl_pct:+.1f}%</td>
                        <td>{award_emoji} {award}</td>
                    </tr>
                    """
                except Exception as e:
                    html += f"""
                    <tr>
                        <td><strong>{ticker}</strong></td>
                        <td colspan="6">Error loading position data: {str(e)}</td>
                    </tr>
                    """

            pnl_class = 'positive' if total_unrealized > 0 else 'negative'
            html += f"""
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td colspan="4">TOTAL UNREALIZED P&L</td>
                    <td style="color: {'#27ae60' if total_unrealized > 0 else '#e74c3c'};" colspan="3">${total_unrealized:+,.2f}</td>
                </tr>
            </table>
            """
        else:
            html += "<p>No active positions</p>"

        return html

    except Exception as e:
        return generate_error_section_html("Active Positions", str(e), traceback.format_exc())


def safe_generate_trades_section(strategy, current_date):
    """Safely generate today's trades section with error handling"""
    try:
        today_trades = [t for t in strategy.profit_tracker.closed_trades
                        if t.get('exit_date') and t['exit_date'].date() == current_date.date()]

        html = f"""
        <h3>🔄 Today's Closed Trades ({len(today_trades)})</h3>
        """

        if today_trades:
            html += """
            <table>
                <tr>
                    <th>Ticker</th>
                    <th>Qty</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>P&L</th>
                    <th>%</th>
                    <th>Signal</th>
                </tr>
            """

            total_realized_today = 0
            winners_today = 0

            for trade in today_trades:
                ticker = trade['ticker']
                qty = trade['quantity']
                entry = trade['entry_price']
                exit_price = trade['exit_price']
                pnl = trade['pnl_dollars']
                pnl_pct = trade['pnl_pct']
                signal = trade['entry_signal']

                total_realized_today += pnl
                if pnl > 0:
                    winners_today += 1

                emoji = "✅" if pnl > 0 else "❌"

                html += f"""
                <tr>
                    <td>{emoji} <strong>{ticker}</strong></td>
                    <td>{qty:,}</td>
                    <td>${entry:.2f}</td>
                    <td>${exit_price:.2f}</td>
                    <td style="color: {'#27ae60' if pnl > 0 else '#e74c3c'}; font-weight: bold;">${pnl:+,.2f}</td>
                    <td style="color: {'#27ae60' if pnl_pct > 0 else '#e74c3c'}; font-weight: bold;">{pnl_pct:+.1f}%</td>
                    <td>{signal}</td>
                </tr>
                """

            today_wr = (winners_today / len(today_trades) * 100) if len(today_trades) > 0 else 0

            html += f"""
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td colspan="4">TODAY'S REALIZED P&L</td>
                    <td style="color: {'#27ae60' if total_realized_today > 0 else '#e74c3c'};" colspan="3">${total_realized_today:+,.2f} ({winners_today}/{len(today_trades)} wins, {today_wr:.1f}%)</td>
                </tr>
            </table>
            """
        else:
            html += "<p>No trades closed today</p>"

        return html

    except Exception as e:
        return generate_error_section_html("Today's Closed Trades", str(e), traceback.format_exc())


def safe_generate_rotation_section(strategy):
    """Safely generate rotation section with error handling"""
    try:
        html = """
        <h3>🏆 Stock Rotation Status</h3>
        <table>
            <tr>
                <th>Award Type</th>
                <th>Multiplier</th>
                <th>Count</th>
            </tr>
        """

        award_counts = {}
        for award in strategy.stock_rotator.ticker_awards.values():
            award_counts[award] = award_counts.get(award, 0) + 1

        for award_type in ['premium', 'standard', 'trial', 'none', 'frozen']:
            count = award_counts.get(award_type, 0)
            emoji = {
                'premium': '🥇',
                'standard': '🥈',
                'trial': '🔬',
                'none': '⚪',
                'frozen': '❄️'
            }.get(award_type, '❓')

            multiplier = {
                'premium': '1.3x',
                'standard': '1.0x',
                'trial': '1.0x',
                'none': '0.6x',
                'frozen': '0.0x'
            }.get(award_type, 'N/A')

            html += f"""
            <tr>
                <td>{emoji} {award_type.title()}</td>
                <td>{multiplier}</td>
                <td>{count}</td>
            </tr>
            """

        html += "</table>"
        return html

    except Exception as e:
        return generate_error_section_html("Stock Rotation Status", str(e), traceback.format_exc())


def safe_generate_performance_section(strategy):
    """Safely generate performance section with error handling"""
    try:
        total_trades = len(strategy.profit_tracker.closed_trades)

        if total_trades == 0:
            return "<p>No closed trades yet</p>"

        total_wins = sum(1 for t in strategy.profit_tracker.closed_trades if t['pnl_dollars'] > 0)
        overall_wr = (total_wins / total_trades * 100)
        total_realized = sum(t['pnl_dollars'] for t in strategy.profit_tracker.closed_trades)

        html = f"""
        <div style="background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin: 10px 0;">
            <h3>📊 Overall Performance</h3>
            <table>
                <tr><td><strong>Total Trades:</strong></td><td>{total_trades}</td></tr>
                <tr><td><strong>Win Rate:</strong></td><td style="color: {'#27ae60' if overall_wr >= 50 else '#e74c3c'}; font-weight: bold;">{total_wins}/{total_trades} ({overall_wr:.1f}%)</td></tr>
                <tr><td><strong>Total Realized P&L:</strong></td><td style="color: {'#27ae60' if total_realized > 0 else '#e74c3c'}; font-weight: bold;">${total_realized:+,.2f}</td></tr>
            </table>
        </div>
        """

        return html

    except Exception as e:
        return generate_error_section_html("Overall Performance", str(e), traceback.format_exc())


def safe_generate_top_performers_section(strategy):
    """Safely generate top performers section with error handling"""
    try:
        total_trades = len(strategy.profit_tracker.closed_trades)

        if total_trades == 0:
            return ""

        ticker_stats = {}
        for trade in strategy.profit_tracker.closed_trades:
            ticker = trade['ticker']
            if ticker not in ticker_stats:
                ticker_stats[ticker] = {'trades': 0, 'wins': 0, 'total_pnl': 0}

            ticker_stats[ticker]['trades'] += 1
            if trade['pnl_dollars'] > 0:
                ticker_stats[ticker]['wins'] += 1
            ticker_stats[ticker]['total_pnl'] += trade['pnl_dollars']

        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        html = """
        <h3>💰 Top 10 Performers (All Time)</h3>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Trades</th>
                <th>Win Rate</th>
                <th>Total P&L</th>
                <th>Award</th>
            </tr>
        """

        for ticker, stats in sorted_tickers[:10]:
            trades = stats['trades']
            wins = stats['wins']
            wr = (wins / trades * 100) if trades > 0 else 0
            total_pnl = stats['total_pnl']

            award = strategy.stock_rotator.get_award(ticker)
            award_emoji = {
                'premium': '🥇',
                'standard': '🥈',
                'trial': '🔬',
                'none': '⚪',
                'frozen': '❄️'
            }.get(award, '❓')

            emoji = "✅" if total_pnl > 0 else "❌"

            html += f"""
            <tr>
                <td>{emoji} <strong>{ticker}</strong></td>
                <td>{trades}</td>
                <td style="color: {'#27ae60' if wr >= 50 else '#e74c3c'};">{wr:.1f}%</td>
                <td style="color: {'#27ae60' if total_pnl > 0 else '#e74c3c'}; font-weight: bold;">${total_pnl:+,.2f}</td>
                <td>{award_emoji}</td>
            </tr>
            """

        html += "</table>"
        return html

    except Exception as e:
        return generate_error_section_html("Top Performers", str(e), traceback.format_exc())


def generate_error_section_html(section_name, error, error_traceback):
    """Generate error display for a failed section"""
    return f"""
    <div style="background-color: #fadbd8; padding: 15px; border-left: 5px solid #e74c3c; margin: 10px 0;">
        <h3>❌ {section_name} - Error Loading Data</h3>
        <p><strong>Error:</strong> {error}</p>
        <div style="background-color: #f4f4f4; padding: 10px; border: 1px solid #ddd; font-family: monospace; 
                    font-size: 0.85em; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word;">
            <strong>Full Traceback:</strong><br>
{error_traceback}
        </div>
    </div>
    """


# =============================================================================
# CRASH NOTIFICATION (UNCHANGED)
# =============================================================================

def send_crash_notification(error_message, error_traceback=None):
    """
    Send email notification when bot crashes

    Args:
        error_message: Error message string
        error_traceback: Full traceback string (optional)
    """
    # Skip if backtesting
    if Config.BACKTESTING:
        return

    print("\n[EMAIL] Sending crash notification...")

    try:
        html_body = generate_crash_notification_html(error_message, error_traceback)
        subject = "🚨 TRADING BOT CRASH ALERT"

        send_email(subject, html_body)

    except Exception as e:
        print(f"[EMAIL] Failed to send crash notification: {e}")


def generate_crash_notification_html(error_message, error_traceback=None):
    """
    Generate HTML for crash notification email

    Returns:
        str: HTML content
    """
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            h2 {{ color: #e74c3c; border-bottom: 2px solid #c0392b; padding-bottom: 10px; }}
            .error-box {{ background-color: #fadbd8; padding: 15px; border-left: 5px solid #e74c3c; margin: 10px 0; }}
            .traceback {{ background-color: #f4f4f4; padding: 15px; border: 1px solid #ddd; font-family: monospace; 
                         font-size: 0.9em; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; }}
            .timestamp {{ color: #7f8c8d; font-style: italic; }}
        </style>
    </head>
    <body>
        <h2>🚨 Trading Bot Crash Alert</h2>

        <div class="error-box">
            <h3>Error Message:</h3>
            <p><strong>{error_message}</strong></p>
        </div>

        <p class="timestamp">Timestamp: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p EST')}</p>
    """

    if error_traceback:
        html += f"""
        <h3>Full Traceback:</h3>
        <div class="traceback">
            <pre>{error_traceback}</pre>
        </div>
        """

    html += """
        <hr>
        <p><strong>Action Required:</strong></p>
        <ul>
            <li>Check Railway logs for additional context</li>
            <li>Review error and fix code if needed</li>
            <li>Bot may have automatically restarted (check Railway dashboard)</li>
        </ul>

        <p style="color: #7f8c8d; font-size: 0.9em;">
            <em>Automated alert from SwingTradeStrategy Bot</em>
        </p>
    </body>
    </html>
    """

    return html