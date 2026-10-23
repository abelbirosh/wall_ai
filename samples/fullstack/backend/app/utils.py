import emails


def send_email(to, subject):
    emails.Message(subject=subject, mail_from="app@example.com").send(to=to)
