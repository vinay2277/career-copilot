// Mirrors backend/app/schemas.py. Kept hand-written rather than generated so
// the diff is reviewable; if it drifts, /docs is the source of truth.

export type Proficiency = "none" | "learning" | "working" | "proficient" | "expert";
export type Necessity = "required" | "preferred" | "nice_to_have";
export type Coverage = "have" | "partial" | "missing";
export type SourceKind = "text" | "url" | "pdf" | "image";

export type ApplicationStatus =
  | "saved"
  | "applied"
  | "screening"
  | "interviewing"
  | "offer"
  | "rejected"
  | "withdrawn";

export type InterviewKind = "behavioral" | "technical" | "system_design" | "screening";

export type AccountRole = "student" | "hr" | "admin";

export interface OrganizationSummary {
  id: number;
  name: string;
  is_verified: boolean;
}

export interface Account {
  id: number;
  email: string;
  full_name: string;
  role: AccountRole;
  /** Present for recruiters only. */
  organization: OrganizationSummary | null;
}

export interface SessionState {
  authenticated: boolean;
  account: Account | null;
}

// --------------------------------------------------------------------------
// Published postings — the shared board, distinct from a student's own
// tracked jobs in `Opportunity`.
// --------------------------------------------------------------------------

export type PostingSource = "employer" | "sourced";
export type PostingStatus = "draft" | "open" | "closed";

export interface PostingRequirement {
  name: string;
  necessity: Necessity;
  min_years: number;
  evidence: string | null;
}

export interface Posting {
  id: number;
  title: string;
  company_name: string;
  source: PostingSource;
  status: PostingStatus;
  location: string | null;
  remote: boolean | null;
  seniority: string | null;
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  industry: string | null;
  company_size: string | null;
  description: string | null;
  education: string | null;
  certifications: string[];
  total_years_experience: number | null;
  source_url: string | null;
  requirements: PostingRequirement[];
  closes_at: string | null;
  created_at: string;
}

export interface BoardEntry {
  posting: Posting;
  alignment: Alignment | null;
  applied: boolean;
  application_status: ApplicationStatus | null;
}

export interface Board {
  from_employers: BoardEntry[];
  sourced: BoardEntry[];
}

export interface PostingApplication {
  id: number;
  posting_id: number;
  status: ApplicationStatus;
  alignment_score: number | null;
  alignment_detail: {
    total: number;
    requirements_fit: number;
    preference_fit: number;
    have: string[];
    partial: string[];
    missing: string[];
  } | null;
  cover_note: string | null;
  applied_at: string;
}

export interface MyApplication {
  application: PostingApplication;
  posting: Posting;
}

/** What the extraction agent read out of a pasted description. */
export interface PostingDraft {
  title: string;
  company_name: string | null;
  description: string | null;
  location: string | null;
  remote: boolean | null;
  seniority: string | null;
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  industry: string | null;
  company_size: string | null;
  education: string | null;
  certifications: string[];
  total_years_experience: number | null;
  requirements: PostingRequirement[];
  raw_text: string;
  confidence: number;
  unverified_fields: string[];
  validation_notes: string;
}

/** What gets sent to create or update a posting. */
export interface PostingPayload {
  title: string;
  description?: string | null;
  location?: string | null;
  remote?: boolean | null;
  seniority?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  currency?: string | null;
  industry?: string | null;
  company_size?: string | null;
  education?: string | null;
  certifications?: string[];
  total_years_experience?: number | null;
  closes_at?: string | null;
  requirements: PostingRequirement[];
  raw_text?: string;
}

export interface PostingSummary {
  posting: Posting;
  application_count: number;
  is_accepting: boolean;
}

// --------------------------------------------------------------------------
// Candidates — the recruiter's view of who applied
// --------------------------------------------------------------------------

export interface Candidate {
  application_id: number;
  status: ApplicationStatus;
  applied_at: string;
  cover_note: string | null;

  full_name: string;
  email: string | null;
  phone: string | null;
  headline: string | null;
  location: string | null;
  years_experience: number;

  /** Null when they applied with an empty profile. They are still listed. */
  alignment_score: number | null;
  have: string[];
  partial: string[];
  missing: string[];
  skills: string[];
}

export interface CandidateList {
  posting: Posting;
  candidates: Candidate[];
  status_counts: Record<string, number>;
}

// --------------------------------------------------------------------------
// Administration
// --------------------------------------------------------------------------

export interface AdminOrganization {
  id: number;
  name: string;
  domain: string | null;
  website: string | null;
  is_verified: boolean;
  created_at: string;
  member_count: number;
  posting_count: number;
  member_emails: string[];
}

export interface AdminStats {
  organizations: number;
  awaiting_verification: number;
  students: number;
  recruiters: number;
  open_postings: number;
}

export interface Skill {
  id?: number;
  name: string;
  proficiency: Proficiency;
  years: number;
}

export interface Preferences {
  target_roles: string[];
  locations: string[];
  remote_ok: boolean;
  seniority: string | null;
  min_salary: number | null;
  currency: string;
  company_sizes: string[];
  industries: string[];
}

export interface Profile {
  id: number;
  full_name: string;
  email: string | null;
  headline: string | null;
  years_experience: number;
  career_goal: string | null;
  location: string | null;
  phone: string | null;
  open_to_work: boolean;
  /** Whether recruiters may find this profile in a candidate search. */
  visible_to_recruiters: boolean;
  skills: Skill[];
  preferences: Preferences | null;
}

/**
 * What gets sent on save.
 *
 * `visible_to_recruiters` is optional and omitting it leaves the stored value
 * alone — the backend treats consent as a deliberate act, not something an
 * unrelated profile edit can flip.
 */
export interface ProfilePayload {
  full_name: string;
  email: string | null;
  headline: string | null;
  years_experience: number;
  career_goal: string | null;
  location?: string | null;
  phone?: string | null;
  open_to_work?: boolean;
  visible_to_recruiters?: boolean;
  skills: Skill[];
  preferences: Preferences | null;
}

// --------------------------------------------------------------------------
// Candidate search
// --------------------------------------------------------------------------

export interface CandidateSearchQuery {
  skills?: string[];
  min_years?: number | null;
  location?: string | null;
  remote_only?: boolean;
  open_to_work_only?: boolean;
  limit?: number;
}

export interface CandidateSearchRow {
  profile_id: number;
  full_name: string;
  email: string | null;
  headline: string | null;
  location: string | null;
  years_experience: number;
  open_to_work: boolean;
  /** Null when the search named no skills — nothing to score against. */
  score: number | null;
  have: string[];
  partial: string[];
  missing: string[];
  skills: string[];
}

export interface CandidateSearchResult {
  results: CandidateSearchRow[];
  /** How many profiles are opted in at all, so empty can explain itself. */
  searchable_total: number;
}

export interface Requirement {
  name: string;
  necessity: Necessity;
  min_years: number;
  evidence: string | null;
}

export interface ExtractionPreview {
  title: string;
  company: string | null;
  location: string | null;
  remote: boolean | null;
  seniority: string | null;
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  industry: string | null;
  company_size: string | null;
  description: string | null;
  requirements: Requirement[];
  /** Screening criteria, held apart from requirements so they never score. */
  education?: string | null;
  certifications?: string[];
  total_years_experience?: number | null;
  source_kind: SourceKind;
  source_url: string | null;
  raw_text: string;
  confidence: number;
  unverified_fields: string[];
  contradicted_fields: string[];
  validation_notes: string;
  needs_confirmation: boolean;
}

export interface Job {
  id: number;
  title: string;
  company: string;
  location: string | null;
  remote: boolean | null;
  seniority: string | null;
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  industry: string | null;
  company_size: string | null;
  description: string | null;
  /** Screening criteria, held apart from requirements so they never score. */
  education: string | null;
  certifications: string[];
  total_years_experience: number | null;
  source_kind: SourceKind;
  source_url: string | null;
  extraction_confidence: number;
  unverified_fields: string[];
  requirements: Requirement[];
  created_at: string;
}

export interface RequirementBreakdown {
  name: string;
  necessity: Necessity;
  coverage: Coverage;
  weight: number;
  credit: number;
  reason: string;
}

export interface FacetBreakdown {
  name: string;
  matched: boolean;
  detail: string;
}

export interface Alignment {
  total: number;
  requirements_fit: number;
  preference_fit: number;
  requirements: RequirementBreakdown[];
  facets: FacetBreakdown[];
  explanation: string;
}

export interface Opportunity {
  job: Job;
  alignment: Alignment | null;
  application_id: number | null;
  status: ApplicationStatus | null;
  applied_at: string | null;
  deadline: string | null;
  notes: string | null;
}

export interface SkillROI {
  skill: string;
  demand: number;
  mean_gain: number;
  best_gain: number;
  best_job_id: number | null;
  unlocks: number[];
  unlock_count: number;
  weighted_demand: number;
}

export interface Scenario {
  add_skills?: string[];
  add_at?: Proficiency;
  remove_skills?: string[];
  min_salary?: number | null;
  remote_ok?: boolean | null;
  seniority?: string | null;
  locations?: string[] | null;
}

export interface JobDelta {
  job_id: number;
  title: string;
  company: string;
  before: number;
  after: number;
  change: number;
  newly_in_reach: boolean;
  fell_out_of_reach: boolean;
}

export interface Simulation {
  mean_before: number;
  mean_after: number;
  mean_change: number;
  in_reach_before: number;
  in_reach_after: number;
  deltas: JobDelta[];
}

export interface Stage {
  status: ApplicationStatus;
  reached: number;
  conversion_from_previous: number | null;
  median_days_in_stage: number | null;
}

export interface Stagnant {
  application_id: number;
  job_title: string;
  company: string;
  status: ApplicationStatus;
  days_idle: number;
  threshold: number;
}

export interface Funnel {
  total: number;
  stages: Stage[];
  stagnant: Stagnant[];
  response_rate: number | null;
  offer_rate: number | null;
  median_days_to_response: number | null;
  bottleneck: Stage | null;
}

export interface Action {
  kind: string;
  title: string;
  rationale: string;
  job_id: number | null;
  skill: string | null;
  priority: number;
  estimated_effort: string | null;
}

export interface Guidance {
  headline: string;
  actions: Action[];
  funnel_read: string | null;
  missing_information: string[];
}

export interface Resume {
  id: number;
  filename: string;
  ats_score: number | null;
  strengths: string[] | null;
  gaps: string[] | null;
  analysis_notes: string | null;
  is_primary: boolean;
  created_at: string;
}

/** What uploading a resume did to the profile. */
export interface ProfileUpdate {
  applied: boolean;
  summary: string;
  field_changes: string[];
  skills_added: string[];
  skills_raised: string[];
  /** Named by the resume but already at or above that level on the profile. */
  skills_unchanged: string[];
  /** Dropped for lack of a supporting quote in the resume. */
  skills_rejected: string[];
  education: string[];
  certifications: string[];
  notes: string[];
}

export interface ResumeUpload {
  resume: Resume;
  profile_update: ProfileUpdate | null;
}

export interface TailoredResume {
  id: number;
  job_id: number;
  content: string;
  emphasized_skills: string[];
  change_summary: string | null;
  created_at: string;
}

export interface InterviewTurn {
  id: number;
  position: number;
  question: string;
  answer: string | null;
  score: number | null;
  feedback: string | null;
  improvements: string[] | null;
  probes_skill: string | null;
}

export interface InterviewSession {
  id: number;
  job_id: number | null;
  kind: InterviewKind;
  overall_score: number | null;
  summary: string | null;
  created_at: string;
  completed_at: string | null;
  turns: InterviewTurn[];
}

export interface LearningStep {
  id: number;
  position: number;
  title: string;
  skill: string;
  estimated_hours: number;
  resource_url: string | null;
  proof_of_work: string | null;
  completed: boolean;
}

export interface LearningPath {
  id: number;
  title: string;
  target_skills: string[];
  rationale: string | null;
  created_at: string;
  steps: LearningStep[];
}

/** The alignment score at which a job counts as in reach. Matches skill_roi.py. */
export const UNLOCK_THRESHOLD = 70;
