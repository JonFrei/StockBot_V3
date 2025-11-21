"""
Standalone Email Test Script

Tests email configuration without running the full trading bot.
This helps diagnose if the issue is with email setup or bot logic.

Usage:
    python test_email.py
"""

import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get credentials
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECIPIENT = os.getenv('EMAIL_RECIPIENT')

print("=" * 80)
print("EMAIL CONFIGURATION TEST")
print("=" * 80)
print(f"Sender: {EMAIL_SENDER}")
print(f"Password: {'*' * len(EMAIL_PASSWORD) if EMAIL_PASSWORD else 'NOT SET'}")
print(f"Recipient: {EMAIL_RECIPIENT}")
print("=" * 80)

# Check if all credentials are set
if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT]):
    print("\n❌ ERROR: Missing email configuration!")
    print("\nRequired environment variables:")
    print("  - EMAIL_SENDER (your Gmail address)")
    print("  - EMAIL_PASSWORD (Gmail App Password - NOT your regular password)")
    print("  - EMAIL_RECIPIENT (where to send reports)")
    print("\n📖 How to get a Gmail App Password:")
    print("  1. Enable 2FA on your Google account")
    print("  2. Go to: https://myaccount.google.com/apppasswords")
    print("  3. Create an app password for 'Mail'")
    print("  4. Use that 16-character password (no spaces)")
    exit(1)

print("\n✅ All credentials are set. Testing SMTP connection...\n")

# Try to send test email
try:
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    # Create test message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🧪 Trading Bot Email Test - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT

    # Plain text version
    text_content = """
    This is a test email from your trading bot.

    If you're reading this, your email configuration is working correctly!

    Configuration:
    - SMTP Server: smtp.gmail.com:465 (SSL)
    - Sender: {}
    - Recipient: {}

    Next steps:
    - Verify you received this at the correct address
    - Check spam folder if not in inbox
    - If this works, your bot's email summaries should work too

    Generated: {}
    """.format(EMAIL_SENDER, EMAIL_RECIPIENT, datetime.now().strftime('%Y-%m-%d %I:%M:%S %p'))

    # HTML version
    html_content = """
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; }}
            .content {{ padding: 20px; background-color: #f9f9f9; }}
            .success {{ color: #4CAF50; font-weight: bold; }}
            .info-box {{ background-color: white; padding: 15px; border-left: 4px solid #4CAF50; margin: 10px 0; }}
            .footer {{ padding: 10px; text-align: center; color: #777; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🧪 Trading Bot Email Test</h1>
        </div>

        <div class="content">
            <p class="success">✅ SUCCESS! Your email configuration is working correctly.</p>

            <div class="info-box">
                <h3>Configuration Details:</h3>
                <ul>
                    <li><strong>SMTP Server:</strong> smtp.gmail.com:465 (SSL)</li>
                    <li><strong>Sender:</strong> {}</li>
                    <li><strong>Recipient:</strong> {}</li>
                    <li><strong>Test Time:</strong> {}</li>
                </ul>
            </div>

            <h3>What This Means:</h3>
            <p>If you're reading this email, your trading bot's email notification system is properly configured 
            and can successfully send emails. Daily trading summaries should work the same way.</p>

            <h3>Next Steps:</h3>
            <ol>
                <li>Verify you received this at the correct address</li>
                <li>Check your spam/junk folder if not in inbox</li>
                <li>Add sender to contacts to ensure future emails arrive in inbox</li>
                <li>Run your trading bot and wait for the next daily summary</li>
            </ol>
        </div>

        <div class="footer">
            <p><em>Automated test message from SwingTradeStrategy Bot</em></p>
        </div>
    </body>
    </html>
    """.format(EMAIL_SENDER, EMAIL_RECIPIENT, datetime.now().strftime('%Y-%m-%d %I:%M:%S %p'))

    # Attach both versions
    part1 = MIMEText(text_content, 'plain')
    part2 = MIMEText(html_content, 'html')
    msg.attach(part1)
    msg.attach(part2)

    # Send email
    print("Connecting to Gmail SMTP server...")
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        print("Logging in...")
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)

        print("Sending test email...")
        smtp.send_message(msg)

    print("\n" + "=" * 80)
    print("✅ SUCCESS! Test email sent successfully!")
    print("=" * 80)
    print(f"\nCheck your inbox at: {EMAIL_RECIPIENT}")
    print("(Also check spam/junk folder)")
    print("\nIf you received the email, your configuration is correct.")
    print("The bot's daily summaries should work the same way.")
    print("=" * 80)

except smtplib.SMTPAuthenticationError as e:
    print("\n" + "=" * 80)
    print("❌ AUTHENTICATION FAILED")
    print("=" * 80)
    print(f"\nError: {e}")
    print("\n🔧 Common fixes:")
    print("  1. Make sure you're using an App Password, NOT your regular Gmail password")
    print("  2. App Password setup:")
    print("     - Enable 2-Factor Authentication on your Google account")
    print("     - Go to: https://myaccount.google.com/apppasswords")
    print("     - Create a new App Password for 'Mail'")
    print("     - Copy the 16-character password (remove spaces)")
    print("     - Use that as your EMAIL_PASSWORD")
    print("  3. Verify EMAIL_SENDER matches the Google account that created the App Password")
    print("=" * 80)

except smtplib.SMTPException as e:
    print("\n" + "=" * 80)
    print("❌ SMTP ERROR")
    print("=" * 80)
    print(f"\nError: {e}")
    print("\n🔧 Possible issues:")
    print("  - Gmail SMTP might be temporarily unavailable")
    print("  - Check your internet connection")
    print("  - Verify firewall isn't blocking port 465")
    print("=" * 80)

except Exception as e:
    print("\n" + "=" * 80)
    print("❌ UNEXPECTED ERROR")
    print("=" * 80)
    print(f"\nError: {e}")
    print(f"Error type: {type(e).__name__}")
    print("\nPlease share this error for help debugging.")
    print("=" * 80)

    import traceback

    print("\nFull traceback:")
    traceback.print_exc()