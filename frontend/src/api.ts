import type {
  AdminOrganization,
  AdminStats,
  Board,
  Candidate,
  CandidateList,
  CandidateSearchQuery,
  CandidateSearchResult,
  ProfilePayload,
  ModuleAttempt,
  ModuleDetail,
  ModuleRow,
  Screening,
  BoardEntry,
  MyApplication,
  Posting,
  PostingApplication,
  PostingDraft,
  PostingPayload,
  PostingSummary,
  Funnel,
  Guidance,
  InterviewKind,
  InterviewSession,
  InterviewTurn,
  LearningPath,
  Profile,
  ProfileUpdate,
  Resume,
  ResumeUpload,
  Scenario,
  SessionState,
  Simulation,
  SkillROI,
  TailoredResume,
} from "./types";

// Empty in dev: vite proxies /api to the backend, so relative URLs work.
const BASE = import.meta.env.VITE_API_BASE ?? "";

/** An API error carrying the backend's `detail` message, which is user-facing. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: init?.body instanceof FormData ? {} : { "Content-Type": "application/json" },
      // Send the session cookie. Same-origin in production, and required
      // explicitly when the dev server proxies from a different port.
      credentials: "include",
      ...init,
    });
  } catch {
    throw new ApiError("Could not reach the backend. Is it running on :8000?", 0);
  }

  // A 401 anywhere means the session went away — expired, or the server
  // restarted without a stable SECRET_KEY. Tell the shell so it can show the
  // login screen, rather than surfacing "Not signed in" on whatever page the
  // user happened to be looking at.
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("career-copilot:unauthenticated"));
  }

  if (!response.ok) {
    // FastAPI returns {detail: "..."} for HTTPException and {detail: [...]} for
    // validation errors. Both are surfaced rather than replaced with a generic
    // message — the backend writes these to be read.
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((e: { loc?: string[]; msg?: string }) =>
            `${e.loc?.slice(1).join(".") ?? "field"}: ${e.msg ?? "invalid"}`,
          )
          .join("; ");
      }
    } catch {
      // Non-JSON error body; keep the status-based message.
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

const upload = <T,>(path: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return request<T>(path, { method: "POST", body: form });
};

export interface Health {
  status: string;
  provider: "openai" | "anthropic";
  model: string;
  /** False when the backend has no credentials for the active provider. */
  ai_available: boolean;
  ai_note: string | null;
}

export const api = {
  health: () => request<Health>("/health"),

  // --- Auth ---
  session: () => request<SessionState>("/api/auth/session"),
  login: (email: string, password: string) =>
    post<SessionState>("/api/auth/login", { email, password }),
  registerStudent: (email: string, password: string, full_name: string) =>
    post<SessionState>("/api/auth/register/student", {
      email,
      password,
      full_name,
    }),
  registerHr: (
    email: string,
    password: string,
    full_name: string,
    organization_name: string,
  ) =>
    post<SessionState>("/api/auth/register/hr", {
      email,
      password,
      full_name,
      organization_name,
    }),
  logout: () => post<SessionState>("/api/auth/logout"),
  changePassword: (current_password: string, new_password: string) =>
    post<SessionState>("/api/auth/password", { current_password, new_password }),

  // --- Student job board ---
  board: (opts?: { minScore?: number; breakdown?: boolean }) => {
    const q = new URLSearchParams();
    if (opts?.minScore != null) q.set("min_score", String(opts.minScore));
    if (opts?.breakdown) q.set("include_breakdown", "true");
    const suffix = q.toString() ? `?${q}` : "";
    return request<Board>(`/api/board${suffix}`);
  },
  posting: (id: number) => request<BoardEntry>(`/api/board/postings/${id}`),
  apply: (id: number, cover_note?: string) =>
    post<PostingApplication>(`/api/board/postings/${id}/apply`, {
      cover_note: cover_note || null,
    }),
  myApplications: () => request<MyApplication[]>("/api/board/applications"),

  // --- Screening interview ---
  startInterview: (applicationId: number) =>
    post<Screening>(`/api/board/applications/${applicationId}/interview`),
  readInterview: (applicationId: number) =>
    request<Screening>(`/api/board/applications/${applicationId}/interview`),
  submitInterview: (applicationId: number, answers: Record<number, string>) =>
    post<Screening>(
      `/api/board/applications/${applicationId}/interview/submit`,
      { answers },
    ),
  withdraw: (applicationId: number) =>
    request<void>(`/api/board/applications/${applicationId}`, {
      method: "DELETE",
    }),

  // --- Recruiter postings ---
  parseDescription: (text: string) =>
    post<PostingDraft>("/api/employer/postings/parse", { text }),
  parseUrl: (url: string) =>
    post<PostingDraft>("/api/employer/postings/parse/url", { url }),
  parsePdf: (file: File) =>
    upload<PostingDraft>("/api/employer/postings/parse/pdf", file),
  parseImage: (file: File) =>
    upload<PostingDraft>("/api/employer/postings/parse/image", file),
  createPosting: (payload: PostingPayload) =>
    post<Posting>("/api/employer/postings", payload),
  myPostings: () => request<PostingSummary[]>("/api/employer/postings"),
  getPosting: (id: number) => request<PostingSummary>(`/api/employer/postings/${id}`),
  updatePosting: (id: number, payload: PostingPayload) =>
    request<Posting>(`/api/employer/postings/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  publishPosting: (id: number) => post<Posting>(`/api/employer/postings/${id}/publish`),
  closePosting: (id: number) => post<Posting>(`/api/employer/postings/${id}/close`),
  deletePosting: (id: number) =>
    request<void>(`/api/employer/postings/${id}`, { method: "DELETE" }),

  // --- Candidates ---
  candidates: (postingId: number) =>
    request<CandidateList>(`/api/employer/postings/${postingId}/applications`),
  decideOnCandidate: (postingId: number, applicationId: number, status: string) =>
    request<Candidate>(
      `/api/employer/postings/${postingId}/applications/${applicationId}`,
      { method: "PATCH", body: JSON.stringify({ status }) },
    ),
  /**
   * The export URL, for an <a download>. Not fetched: letting the browser make
   * the request is what gives the user a real Save dialog and the filename the
   * server chose. The session cookie rides along because it is same-origin.
   */
  candidatesCsvUrl: (postingId: number) =>
    `${BASE}/api/employer/postings/${postingId}/applications.csv`,
  searchCandidates: (query: CandidateSearchQuery) =>
    post<CandidateSearchResult>("/api/employer/candidates/search", query),

  // --- Administration ---
  adminStats: () => request<AdminStats>("/api/admin/stats"),
  adminOrganizations: (pendingOnly = false) =>
    request<AdminOrganization[]>(
      `/api/admin/organizations${pendingOnly ? "?pending_only=true" : ""}`,
    ),
  verifyOrganization: (id: number) =>
    post<AdminOrganization>(`/api/admin/organizations/${id}/verify`),
  unverifyOrganization: (id: number) =>
    post<AdminOrganization>(`/api/admin/organizations/${id}/unverify`),

  // --- Profile ---
  getProfile: () => request<Profile>("/api/profile"),
  saveProfile: (payload: ProfilePayload) =>
    request<Profile>("/api/profile", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // --- Analytics ---
  skillRoi: (limit = 10) => request<SkillROI[]>(`/api/skill-roi?limit=${limit}`),
  whatIf: (scenario: Scenario) => post<Simulation>("/api/simulation/what-if", scenario),
  funnel: () => request<Funnel>("/api/analytics/funnel"),
  actionCenter: () => request<Guidance>("/api/analytics/action-center"),
  debugContext: () => request<{ context: string }>("/api/analytics/context"),

  // --- Resume ---
  listResumes: () => request<Resume[]>("/api/resume"),
  /** Uploads, analyzes, and (unless disabled) populates the profile from it. */
  uploadResume: (file: File, updateProfile = true) =>
    upload<ResumeUpload>(
      `/api/resume?update_profile=${updateProfile}`,
      file,
    ),
  reanalyzeResume: (id: number) => post<Resume>(`/api/resume/${id}/reanalyze`),
  applyResumeToProfile: (id: number) =>
    post<ProfileUpdate>(`/api/resume/${id}/to-profile`),
  tailorResume: (jobId: number) => post<TailoredResume>(`/api/resume/tailor/${jobId}`),
  listTailored: (jobId: number) =>
    request<TailoredResume[]>(`/api/resume/tailored/${jobId}`),

  // --- Interview ---
  listSessions: () => request<InterviewSession[]>("/api/interview"),
  startSession: (jobId: number, kind: InterviewKind, questionCount = 5) =>
    post<InterviewSession>("/api/interview", {
      job_id: jobId,
      kind,
      question_count: questionCount,
    }),
  getSession: (id: number) => request<InterviewSession>(`/api/interview/${id}`),
  submitAnswer: (sessionId: number, position: number, answer: string) =>
    post<InterviewTurn>(`/api/interview/${sessionId}/turns/${position}/answer`, { answer }),
  completeSession: (id: number) => post<InterviewSession>(`/api/interview/${id}/complete`),

  // --- The Gen AI course ---
  modules: () => request<ModuleRow[]>("/api/modules"),
  module: (slug: string) => request<ModuleDetail>(`/api/modules/${slug}`),
  attemptModule: (slug: string, answers: Record<number, number>) =>
    post<ModuleAttempt>(`/api/modules/${slug}/attempt`, { answers }),

  // --- Learning ---
  listPaths: () => request<LearningPath[]>("/api/learning"),
  generateRoadmap: (skillCount = 3, hoursPerWeek = 6) =>
    post<LearningPath>("/api/learning/roadmap", {
      skill_count: skillCount,
      hours_per_week: hoursPerWeek,
    }),
  toggleStep: (stepId: number, completed: boolean) =>
    request<LearningPath>(`/api/learning/steps/${stepId}?completed=${completed}`, {
      method: "PATCH",
    }),
  deletePath: (id: number) => request<void>(`/api/learning/${id}`, { method: "DELETE" }),
};
