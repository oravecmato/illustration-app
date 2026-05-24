// ── Chat & sessions ────────────────────────────────────────────────────────

export type CharacterRole = "male" | "female" | "mother";

export type ChatPhase = "gathering" | "awaiting_confirmation" | "confirmed";

export type SessionState =
  | "CHATTING"
  | "AWAITING_CONFIRMATION"
  | "FINALIZING"
  | "FINALIZED"
  | "FAILED";

export type MessageRole = "user" | "assistant";

export interface BriefCharacter {
  role: CharacterRole;
  name_in_story: string;
  short_description: string;
}

export interface CollectedBrief {
  characters: BriefCharacter[];
  topic: string;
  notes: string;
}

export interface SessionMessage {
  id: string;
  role: MessageRole;
  content: string;
  created_at: string;
}

export interface Session {
  id: string;
  state: SessionState;
  collected_brief: CollectedBrief | null;
  run_id: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  messages: SessionMessage[];
}

export interface PostMessageResponse {
  session: Session;
  phase: ChatPhase;
}

// ── Runs ───────────────────────────────────────────────────────────────────

export type RunStatus = "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export type IllustrationState =
  | "PENDING"
  | "GENERATING_PROMPTS"
  | "RENDERING"
  | "EVALUATING"
  | "REVISING_PROMPTS"
  | "RETHINKING_CONCEPT"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface StyleGuide {
  overall_style_positive: string;
  overall_style_negative: string;
  character_lora: string;
  character_baseline_description: string;
}

export type StoryBlock =
  | { type: "paragraph"; text: string }
  | { type: "illustration"; scene_index: number };

export interface Run {
  id: string;
  session_id: string;
  status: RunStatus;
  story_title: string;
  story_blocks: StoryBlock[];
  style_guide: StyleGuide;
  illustration_count: number;
  completed_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
  error_code: string | null;
  error_message: string | null;
}

export interface Illustration {
  id: string;
  scene_index: number;
  scene_excerpt: string;
  character_role: CharacterRole;
  current_concept: string;
  state: IllustrationState;
  concept_attempt: number;
  prompt_attempt: number;
  image_url: string | null;
}

// SSE event payloads
export interface SnapshotEvent {
  run: Run;
  illustrations: Illustration[];
}

export interface IllustrationStateEvent {
  illustration_id: string;
  scene_index: number;
  state: IllustrationState;
  concept_attempt: number;
  prompt_attempt: number;
}

export interface IllustrationCompletedEvent {
  illustration_id: string;
  scene_index: number;
  image_url: string;
}

export interface IllustrationFailedEvent {
  illustration_id: string;
  scene_index: number;
  error_message: string;
}

export interface RunCompletedEvent {
  completed: number;
  failed: number;
}

export interface RunFailedEvent {
  error_code: string;
  error_message: string;
}

export type SseEvent =
  | { type: "snapshot"; data: SnapshotEvent }
  | { type: "illustration_state"; data: IllustrationStateEvent }
  | { type: "illustration_completed"; data: IllustrationCompletedEvent }
  | { type: "illustration_failed"; data: IllustrationFailedEvent }
  | { type: "run_completed"; data: RunCompletedEvent }
  | { type: "run_failed"; data: RunFailedEvent }
  | { type: "run_cancelled"; data: Record<string, never> }
  | { type: "heartbeat"; data: Record<string, never> };
