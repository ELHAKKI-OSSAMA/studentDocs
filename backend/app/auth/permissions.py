import enum


class Perm(enum.StrEnum):
    """Permission codes. Role → permission mapping lives in the `role_permissions` table."""

    PROFILE_SELF = "profile.self"
    ENROLLMENT_SELF = "enrollment.self"
    CATALOG_READ = "catalog.read"
    ADMIN_ACCESS = "admin.access"
    DASHBOARD_READ = "dashboard.read"
    STUDENTS_READ = "students.read"
    STUDENTS_MANAGE = "students.manage"
    USERS_READ = "users.read"
    CATALOG_MANAGE = "catalog.manage"
    USERS_MANAGE = "users.manage"
    SETTINGS_MANAGE = "settings.manage"
    REQUEST_CREATE = "request.create"
    REQUEST_READ_OWN = "request.read_own"
    REQUESTS_READ = "requests.read"
    REQUESTS_PROCESS = "requests.process"
    REQUESTS_ASSIGN = "requests.assign"
    REQUESTS_APPROVE = "requests.approve"
    REQUESTS_REJECT = "requests.reject"
    ENROLLMENTS_VERIFY = "enrollments.verify"
    # Inbound email review (Phase 4)
    EMAILS_READ = "emails.read"
    EMAILS_READ_RAW = "emails.read_raw"
    EMAILS_PROCESS = "emails.process"
    EMAILS_CONVERT = "emails.convert"
    EMAILS_DISMISS = "emails.dismiss"
    EMAIL_ACCOUNTS_MANAGE = "email_accounts.manage"
