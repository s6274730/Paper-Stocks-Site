import smtplib
from email.mime.text import MIMEText

smtp_host = 'smtp.gmail.com'
smtp_port = 465
from_address = 'BullsEyeAutoMails@gmail.com'
db = "users.db"
app_password = "rvxw xbin sghn viyg"

template = """Hi {name},

Welcome to Bull's Eye. Please confirm your email address by clicking the link below:

{link}

If you didn't create an account, ignore this message.

— Bull's Eye
"""


def send_verification(to_email, name, link):
    body = template.format(name=name, link=link)
    msg = MIMEText(body)
    msg["Subject"] = "Confirm your Bull's Eye email"
    msg["From"] = from_address
    msg["To"] = to_email

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(from_address, app_password)
        server.sendmail(from_address, [to_email], msg.as_string())
