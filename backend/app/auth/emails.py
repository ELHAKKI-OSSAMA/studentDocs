from app.core.mailer import OutgoingEmail
from app.users.models import Locale

_VERIFY = {
    Locale.FR: (
        "Confirmez votre adresse email",
        "Bonjour {name},\n\nPour activer votre compte StudentDocs, ouvrez ce lien :\n{link}\n\n"
        "Ce lien expire dans {hours} heures. Si vous n'êtes pas à l'origine de cette inscription, "
        "ignorez ce message.",
    ),
    Locale.EN: (
        "Confirm your email address",
        "Hello {name},\n\nTo activate your StudentDocs account, open this link:\n{link}\n\n"
        "This link expires in {hours} hours. If you did not sign up, ignore this message.",
    ),
    Locale.AR: (
        "تأكيد عنوان بريدك الإلكتروني",
        "مرحبا {name}،\n\nلتفعيل حسابك على StudentDocs، افتح هذا الرابط:\n{link}\n\n"
        "تنتهي صلاحية هذا الرابط خلال {hours} ساعة. إذا لم تقم بالتسجيل، تجاهل هذه الرسالة.",
    ),
}


def verification_email(*, to: str, name: str, locale: Locale, link: str, ttl_seconds: int) -> OutgoingEmail:
    subject, body = _VERIFY[locale]
    return OutgoingEmail(
        to=to, subject=subject, text=body.format(name=name, link=link, hours=ttl_seconds // 3600)
    )
