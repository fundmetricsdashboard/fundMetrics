import smtplib

EMAIL = "fundmetrics.dashboard@gmail.com"
APP_PASSWORD = "jkhsrqybmgtjahtc"

with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls()
    server.login(EMAIL, APP_PASSWORD)
    print("Login OK")