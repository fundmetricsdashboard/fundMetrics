from flask_mail import Message
from app import mail

def send_password_reset_email(to_email, reset_link):
    msg = Message(
        subject="Dashboard App Password Reset",
        recipients=[to_email],
        body=f"""
Hello,

We received a request to reset your MF Dashboard password.

Click the link below to reset your password:

{reset_link}

If you did not request this, you can safely ignore this email.

Regards,
Dashboard App Support
"""
    )
    mail.send(msg)
