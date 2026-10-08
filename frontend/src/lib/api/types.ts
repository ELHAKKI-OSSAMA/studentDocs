import type { I18nText } from "@/i18n/translate";

export type Role = "STUDENT" | "ADMIN" | "SUPER_ADMIN";
export type Locale = "fr" | "en" | "ar";

export type Me = {
  id: string;
  email: string;
  role: Role;
  first_name: string;
  last_name: string;
  locale: Locale;
  permissions: string[];
  student: { id: string; student_number: string | null } | null;
};

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type Timestamps = { id: string; created_at: string; updated_at: string };

export type CategoryRef = { id: string; code: string; name_i18n: I18nText };

export type AcademicYear = Timestamps & {
  label: string;
  start_date: string;
  end_date: string;
  status: "ACTIVE" | "ARCHIVED";
};

export type BranchCategory = Timestamps & {
  code: string;
  name_i18n: I18nText;
  sort_order: number;
  is_active: boolean;
};

export type Branch = Timestamps & {
  code: string;
  name_i18n: I18nText;
  is_active: boolean;
  category: CategoryRef;
};

export type StudyLevel = Timestamps & {
  code: string;
  name_i18n: I18nText;
  sort_order: number;
  is_active: boolean;
  category: CategoryRef;
};

export type DocumentType = Timestamps & {
  code: string;
  name_i18n: I18nText;
  description_i18n: I18nText | null;
  delivery_mode: "DIGITAL" | "PICKUP";
  requires_attachment: boolean;
  max_quantity: number;
  processing_days: number;
  is_active: boolean;
  allowed_categories: CategoryRef[];
};

export type EnrollmentStatus = "PENDING" | "VERIFIED" | "REJECTED";

export type Enrollment = {
  id: string;
  academic_year: { id: string; label: string; status: string };
  branch: { id: string; code: string; name_i18n: I18nText; category: CategoryRef };
  study_level: { id: string; code: string; name_i18n: I18nText };
  status: EnrollmentStatus;
  source: "SELF_DECLARED" | "ADMIN" | "IMPORT";
  review_note: string | null;
  reviewed_at: string | null;
  created_at: string;
};

export type EnrollmentReviewItem = Enrollment & {
  student_id: string;
  student_name: string;
  student_email: string;
  student_number: string | null;
  reviewer_name: string | null;
};

export type StaffUser = {
  id: string;
  email: string;
  role: Role;
  first_name: string;
  last_name: string;
  is_active: boolean;
  email_verified: boolean;
  last_login_at: string | null;
  created_at: string;
};

export type StudentListItem = {
  id: string;
  user_id: string;
  email: string;
  first_name: string;
  last_name: string;
  student_number: string | null;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
};

export type DashboardStats = {
  students_total: number;
  students_pending_verification: number;
  staff_total: number;
  active_academic_years: number;
  active_branches: number;
  active_document_types: number;
  allowed_email_domains: number;
  requests_today: number;
  requests_open: number;
  requests_unassigned: number;
  requests_needing_information: number;
  requests_assigned_to_me: number;
  enrollments_pending: number;
  requests_by_status: Partial<Record<RequestStatus, number>>;
};

export type EmailDomain = { id: string; domain: string; is_active: boolean; created_at: string };

export const REQUEST_STATUSES = [
  "SUBMITTED",
  "RECEIVED",
  "IN_REVIEW",
  "NEEDS_INFORMATION",
  "PROCESSING",
  "APPROVED",
  "READY_FOR_PICKUP",
  "DOCUMENT_AVAILABLE",
  "COMPLETED",
  "REJECTED",
  "CANCELLED",
] as const;
export type RequestStatus = (typeof REQUEST_STATUSES)[number];

export type DeliveryMode = "DIGITAL" | "PICKUP";

export type RequestDocumentType = {
  id: string;
  code: string;
  name_i18n: I18nText;
  delivery_mode: DeliveryMode;
  requires_attachment: boolean;
};

export type RequestItem = { id: string; quantity: number; document_type: RequestDocumentType };

export type DocumentKind = "ATTACHMENT" | "ISSUED" | "MESSAGE";

export type ScanStatus = "NOT_SCANNED" | "SCANNING" | "CLEAN" | "INFECTED" | "ERROR";

/** File metadata only: the storage location is never exposed, downloads go through the API. */
export type RequestDocument = {
  id: string;
  kind: DocumentKind;
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  scan_status: ScanStatus;
  /** virus_detected, scanner_unavailable, scanner_error, file_missing, scan_failed */
  scan_reason: string | null;
  scanned_at: string | null;
  /** Only CLEAN files can be downloaded. */
  can_download: boolean;
  request_item_id: string | null;
  message_id: string | null;
  created_at: string;
  /** Staff only. */
  original_filename: string | null;
  scan_detail: string | null;
};

export type HistoryEntry = {
  from_status: RequestStatus | null;
  to_status: RequestStatus;
  actor_role: string;
  comment: string | null;
  created_at: string;
};

export type PersonRef = { id: string; first_name: string; last_name: string };

export type RequestStudent = {
  id: string;
  user_id: string;
  first_name: string;
  last_name: string;
  email: string;
  student_number: string | null;
};

export type RequestListItem = {
  id: string;
  reference: string;
  status: RequestStatus;
  source: string;
  priority: string;
  created_at: string;
  updated_at: string;
  academic_year: { id: string; label: string };
  branch: { id: string; code: string; name_i18n: I18nText; category: CategoryRef };
  items: RequestItem[];
  unread_messages: number;
  student: RequestStudent | null;
  assigned_to: PersonRef | null;
};

export type RequestDetail = RequestListItem & {
  study_level: { id: string; code: string; name_i18n: I18nText };
  enrollment_status: EnrollmentStatus;
  reason: string | null;
  extra_info: string | null;
  status_reason: string | null;
  submitted_at: string;
  closed_at: string | null;
  documents: RequestDocument[];
  history: HistoryEntry[];
  available_transitions: RequestStatus[];
  can_cancel: boolean;
  can_respond: boolean;
  can_message: boolean;
  can_assign: boolean;
  can_upload_document: boolean;
};

export type MessageKind = "MESSAGE" | "INFORMATION_REQUEST" | "INFORMATION_RESPONSE";

export type RequestMessage = {
  id: string;
  author_side: "STUDENT" | "STAFF";
  author_name: string;
  kind: MessageKind;
  body: string;
  created_at: string;
  read_at: string | null;
  attachments: RequestDocument[];
};

export type RequestSummary = {
  pending: number;
  in_progress: number;
  action_required: number;
  completed: number;
  closed: number;
};

export type IssuedDocument = RequestDocument & { request_id: string; reference: string };

export type NotificationType =
  | "REQUEST_RECEIVED"
  | "STATUS_CHANGED"
  | "INFORMATION_REQUESTED"
  | "NEW_MESSAGE"
  | "INFORMATION_PROVIDED"
  | "REQUEST_ASSIGNED"
  | "DOCUMENT_INFECTED"
  | "DOCUMENT_SCAN_FAILED";

export type AppNotification = {
  id: string;
  type: NotificationType;
  request_id: string | null;
  reference: string | null;
  status: RequestStatus | null;
  created_at: string;
  read_at: string | null;
};

export const PERMS = {
  adminAccess: "admin.access",
  catalogManage: "catalog.manage",
  usersManage: "users.manage",
  settingsManage: "settings.manage",
  requestsRead: "requests.read",
  requestsProcess: "requests.process",
  enrollmentsVerify: "enrollments.verify",
} as const;
