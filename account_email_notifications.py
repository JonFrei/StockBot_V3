"""
Email Notification System

Sends:
1. Daily trading summary emails (after each trading iteration)
2. Crash notification emails (when bot encounters fatal errors)

Only sends emails during live trading (not backtesting)
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config import Config
import traceback


def send_email(subject, body_html, body_text=None):
    """
    Send email with HTML content

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
    if not all([Config.EMAIL_SENDER, Config.EMAIL_PASSWORD, Config.EMAIL_RECIPIENT]):
        print("[EMAIL] Email not configured - skipping")
        return False

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = Config.EMAIL_SENDER
        msg['To'] = Config.EMAIL_RECIPIENT

        # Attach plain text and HTML versions
        if body_text:
            part1 = MIMEText(body_text, 'plain')
            msg.attach(part1)

        part2 = MIMEText(body_html, 'html')
        msg.attach(part2)

        # Send email via Gmail SMTP
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(Config.EMAIL_SENDER, Config.EMAIL_PASSWORD)
            smtp.send_message(msg)

        print(f"[EMAIL] ✅ Sent: {subject}")
        return True

    except Exception as e:
        print(f"[EMAIL] ❌ Failed to send email: {e}")
        return False


def send_daily_summary_email(strategy, current_date):
    """
    Send comprehensive daily trading summary email

    Args:
        strategy: Lumibot Strategy instance
        current_date: Current datetime object
    """
    # Skip if backtesting
    if Config.BACKTESTING:
        return

    print("\n[EMAIL] Preparing daily summary email...")

    try:
        html_body = generate_daily_summary_html(strategy, current_date)
        subject = f"📊 Trading Summary - {current_date.strftime('%Y-%m-%d')}"

        send_email(subject, html_body)

    except Exception as e:
        print(f"[EMAIL] Error generating daily summary: {e}")


def generate_daily_summary_html(strategy, current_date):
    """
    Generate HTML for daily trading summary

    Returns:
        str: HTML content
    """
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            h3 {{ color: #34495e; margin-top: 20px; }}
            table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
            th {{ background-color: #3498db; color: white; padding: 10px; text-align: left; }}
            td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
            tr:hover {{ background-color: #f5f5f5; }}
            .positive {{ color: #27ae60; font-weight: bold; }}
            .negative {{ color: #e74c3c; font-weight: bold; }}
            .summary-box {{ background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin: 10px 0; }}
            .emoji {{ font-size: 1.2em; }}
        </style>
    </head>
    <body>
        <h2>📊 Daily Trading Summary - {current_date.strftime('%B %d, %Y')}</h2>
    """

    # Portfolio Overview
    cash = strategy.get_cash()
    invested = strategy.portfolio_value - cash

    html += f"""
        <div class="summary-box">
            <h3>💰 Portfolio Status</h3>
            <table>
                <tr><td><strong>Total Value:</strong></td><td>${strategy.portfolio_value:,.2f}</td></tr>
                <tr><td><strong>Cash:</strong></td><td>${cash:,.2f}</td></tr>
                <tr><td><strong>Invested:</strong></td><td>${invested:,.2f}</td></tr>
            </table>
        </div>
    """

    # Active Positions
    positions = strategy.get_positions()
    html += f"""
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
            ticker = position.symbol
            qty = int(position.quantity)
            entry_price = float(getattr(position, 'avg_entry_price', None) or
                                getattr(position, 'avg_fill_price', 0))

            try:
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
                        <td class="{pnl_class}">${pnl_dollars:+,.2f}</td>
                        <td class="{pnl_class}">{pnl_pct:+.1f}%</td>
                        <td>{award_emoji} {award}</td>
                    </tr>
                """
            except:
                html += f"""
                    <tr>
                        <td><strong>{ticker}</strong></td>
                        <td>{qty:,}</td>
                        <td>${entry_price:.2f}</td>
                        <td colspan="4">Price unavailable</td>
                    </tr>
                """

        pnl_class = 'positive' if total_unrealized > 0 else 'negative'
        html += f"""
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td colspan="4">TOTAL UNREALIZED P&L</td>
                    <td class="{pnl_class}" colspan="3">${total_unrealized:+,.2f}</td>
                </tr>
            </table>
        """
    else:
        html += "<p>No active positions</p>"

    # Today's Closed Trades
    today_trades = [t for t in strategy.profit_tracker.closed_trades
                    if t.get('exit_date') and t['exit_date'].date() == current_date.date()]

    html += f"""
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
            pnl_class = 'positive' if pnl > 0 else 'negative'

            html += f"""
                <tr>
                    <td>{emoji} <strong>{ticker}</strong></td>
                    <td>{qty:,}</td>
                    <td>${entry:.2f}</td>
                    <td>${exit_price:.2f}</td>
                    <td class="{pnl_class}">${pnl:+,.2f}</td>
                    <td class="{pnl_class}">{pnl_pct:+.1f}%</td>
                    <td>{signal}</td>
                </tr>
            """

        pnl_class = 'positive' if total_realized_today > 0 else 'negative'
        today_wr = (winners_today / len(today_trades) * 100) if len(today_trades) > 0 else 0

        html += f"""
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td colspan="4">TODAY'S REALIZED P&L</td>
                    <td class="{pnl_class}" colspan="3">${total_realized_today:+,.2f} ({winners_today}/{len(today_trades)} wins, {today_wr:.1f}%)</td>
                </tr>
            </table>
        """
    else:
        html += "<p>No trades closed today</p>"

    # Stock Rotation Summary
    html += """
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

    # Overall Performance
    total_trades = len(strategy.profit_tracker.closed_trades)
    if total_trades > 0:
        total_wins = sum(1 for t in strategy.profit_tracker.closed_trades if t['pnl_dollars'] > 0)
        overall_wr = (total_wins / total_trades * 100)
        total_realized = sum(t['pnl_dollars'] for t in strategy.profit_tracker.closed_trades)

        wr_class = 'positive' if overall_wr >= 50 else 'negative'
        pnl_class = 'positive' if total_realized > 0 else 'negative'

        html += f"""
            <div class="summary-box">
                <h3>📊 Overall Performance</h3>
                <table>
                    <tr><td><strong>Total Trades:</strong></td><td>{total_trades}</td></tr>
                    <tr><td><strong>Win Rate:</strong></td><td class="{wr_class}">{total_wins}/{total_trades} ({overall_wr:.1f}%)</td></tr>
                    <tr><td><strong>Total Realized P&L:</strong></td><td class="{pnl_class}">${total_realized:+,.2f}</td></tr>
                </table>
            </div>
        """

    # Top Performers
    if total_trades > 0:
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

        html += """
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
            pnl_class = 'positive' if total_pnl > 0 else 'negative'
            wr_class = 'positive' if wr >= 50 else 'negative'

            html += f"""
                <tr>
                    <td>{emoji} <strong>{ticker}</strong></td>
                    <td>{trades}</td>
                    <td class="{wr_class}">{wr:.1f}%</td>
                    <td class="{pnl_class}">${total_pnl:+,.2f}</td>
                    <td>{award_emoji}</td>
                </tr>
            """

        html += "</table>"

    html += """
        <hr>
        <p style="color: #7f8c8d; font-size: 0.9em;">
            <em>Generated by SwingTradeStrategy Bot</em><br>
            <em>Timestamp: {}</em>
        </p>
    </body>
    </html>
    """.format(datetime.now().strftime('%Y-%m-%d %I:%M:%S %p EST'))

    return html


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
            .traceback {{ background-color: #f4f4f4; padding: 15px; border: 1px solid #ddd; font-family: monospace; font-size: 0.9em; overflow-x: auto; }}
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