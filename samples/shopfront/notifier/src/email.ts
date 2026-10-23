const SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send";

export async function sendEmail(to: string, message: string) {
  await fetch(SENDGRID_URL, {
    method: "POST",
    body: JSON.stringify({ to, message }),
  });
}
