import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

def send_automated_email(to_email, subject, body):
    """
    Jarvis connects to SMTP to send emails natively from your laptop.
    Note: To actually send emails, you need an App Password from Gmail.
    """
    # In a real environment, Jarvis pulls these from securely stored environment variables
    # export JARVIS_EMAIL="your_email@gmail.com"
    # export JARVIS_EMAIL_PASS="your_app_password"
    
    sender_email = os.environ.get("JARVIS_EMAIL")
    sender_password = os.environ.get("JARVIS_EMAIL_PASS")
    
    if not sender_email or not sender_password:
        return "🛑 [ERROR] Jarvis cannot send the email. Please set your JARVIS_EMAIL and JARVIS_EMAIL_PASS environment variables first."
        
    print(f"📧 [EMAIL] Jarvis is drafting an email to {to_email}...")
    
    # Create the email structure
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject
    
    # Attach the body
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        # Connect to Gmail's server (or change to outlook/yahoo)
        print("🔗 Connecting to SMTP server...")
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls() # Secure the connection
        
        print("🔐 Authenticating...")
        server.login(sender_email, sender_password)
        
        print("🚀 Sending transmission...")
        server.send_message(msg)
        server.quit()
        
        return f"✅ Success! Jarvis sent the email to {to_email}."
    except Exception as e:
        return f"🛑 [ERROR] Failed to send email. Ensure your App Password is correct. Details: {str(e)}"

if __name__ == "__main__":
    # Test script if run directly
    print("Testing email agent...")
    # send_automated_email("target@example.com", "Test from Jarvis", "Hello, I am Jarvis.")
