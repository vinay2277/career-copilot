import type {
  ExtractionPreview,
  Funnel,
  Guidance,
  InterviewKind,
  InterviewSession,
  InterviewTurn,
  Job,
  LearningPath,
  Opportunity,
  Profile,
  ProfileUpdate,
  Resume,
  ResumeUpload,
  Scenario,
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

export interface AuthStatus {
  /** False when no password is configured, i.e. the gate is off entirely. */
  auth_required: boolean;
  authenticated: boolean;
}

export const api = {
  health: () => request<Health>("/health"),

  // --- Auth ---
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  login: (password: string) => post<AuthStatus>("/api/auth/login", { password }),
  logout: () => post<AuthStatus>("/api/auth/logout"),

  // --- Profile ---
  getProfile: () => request<Profile>("/api/profile"),
  saveProfile: (payload: Omit<Profile, "id">) =>
    request<Profile>("/api/profile", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // --- Ingestion ---
  extractText: (text: string) => post<ExtractionPreview>("/api/extract/text", { text }),
  extractUrl: (url: string) => post<ExtractionPreview>("/api/extract/url", { url }),
  extractPdf: (file: File) => upload<ExtractionPreview>("/api/extract/pdf", file),
  extractImage: (file: File) => upload<ExtractionPreview>("/api/extract/image", file),
  confirmExtraction: (preview: ExtractionPreview) =>
    post<Job>("/api/extract/confirm", preview),

  // --- Board ---
  listOpportunities: (params?: { status?: string; minScore?: number; breakdown?: boolean }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.minScore != null) q.set("min_score", String(params.minScore));
    if (params?.breakdown) q.set("include_breakdown", "true");
    const suffix = q.toString() ? `?${q}` : "";
    return request<Opportunity[]>(`/api/opportunities${suffix}`);
  },
  getOpportunity: (jobId: number) => request<Opportunity>(`/api/opportunities/${jobId}`),
  updateApplication: (
    jobId: number,
    payload: { status?: string; notes?: string; deadline?: string },
  ) =>
    request<Opportunity>(`/api/opportunities/${jobId}/application`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteOpportunity: (jobId: number) =>
    request<void>(`/api/opportunities/${jobId}`, { method: "DELETE" }),

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
