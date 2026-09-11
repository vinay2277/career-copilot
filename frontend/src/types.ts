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
  skills: Skill[];
  preferences: Preferences | null;
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
