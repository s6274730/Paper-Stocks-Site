import smtplib
from email.mime.text import MIMEText


class Mailer:
    smtp_host = 'smtp.gmail.com'
    smtp_port = 465
    from_address = 'BullsEyeAutoMails@gmail.com'
    app_password = "rvxw xbin sghn viyg"

    template = """Hi {name},

Welcome to Bull's Eye. Please confirm your email address by clicking the link below:

{link}

If you didn't create an account, ignore this message.

— Bull's Eye
"""

    def send_verification(self, to_email, name, link):
        body = self.template.format(name=name, link=link)
        msg = MIMEText(body)
        msg["Subject"] = "Confirm your Bull's Eye email"
        msg["From"] = self.from_address
        msg["To"] = to_email

        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
            server.login(self.from_address, self.app_password)
            server.sendmail(self.from_address, [to_email], msg.as_string())
