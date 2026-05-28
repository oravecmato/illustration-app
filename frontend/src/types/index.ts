// ── Chat & sessions ────────────────────────────────────────────────────────

export type Language = "sk" | "cs" | "en";

export type TranslationState = "source" | "fresh" | "stale" | "missing";

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

export interface BriefCompanion {
  description: string;
}

export interface CollectedBrief {
  characters: BriefCharacter[];
  companions: BriefCompanion[];
  topic: string;
  notes: string;
}

export interface SessionMessage {
  id: string;
  role: MessageRole;
  content: string;
  created_at: string;
  // Client-only fields for optimistic rendering (§ 9.2.1):
  // - `pending` is true while the POST is in flight and the row hasn't
  //   been reconciled with the server's persisted version yet.
  // - `client_id` is a temporary client-generated id used to locate the
  //   optimistic row when reconciling.
  pending?: boolean;
  client_id?: string;
}

export interface Session {
  id: string;
  state: SessionState;
  source_language: string | null;
  detected_language: string | null;
  topic_short: string | null;
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
  detected_language?: string;
  topic_short?: string;
  /** Pre-allocated run id, returned only when phase === "confirmed".
   *  The frontend uses it to navigate to /runs/:id immediately, while
   *  Agent 0b is still running in a background task on the backend.
   *  The RunView loader stays on screen until SSE delivers the snapshot. */
  run_id?: string | null;
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
  | "MANUAL_CHATTING"
  | "MANUAL_GENERATING_PROMPTS"
  | "MANUAL_RENDERING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type ManualMessageRole = "user" | "assistant" | "image";

export type ManualSubPhase = "concept_design" | "feedback_gathering";

export interface ManualMessage {
  id: string;
  role: ManualMessageRole;
  content: string;
  image_url: string | null;
  manual_attempt_index: number | null;
  // Per-attempt provenance populated only on `role === "image"` rows
  // (legacy rows pre-§6A.10 leave these null → popovers disabled).
  concept_used?: string | null;
  positive_prompt?: string | null;
  negative_prompt?: string | null;
  created_at: string;
  // Client-only fields for optimistic rendering of POSTed user messages.
  pending?: boolean;
  client_id?: string;
}

export interface ManualSessionSummary {
  messages: ManualMessage[];
  manual_attempts: number;
  last_image_url: string | null;
  sub_phase: ManualSubPhase;
}

export interface ManualSessionResponse {
  illustration_id: string;
  state: IllustrationState;
  manual_attempts: number;
  messages: ManualMessage[];
  last_image_url: string | null;
  sub_phase: ManualSubPhase;
}

export interface StyleGuide {
  overall_style_positive: string;
  overall_style_negative: string;
  character_lora: string;
  character_baseline_description: string;
}

export type StoryBlock =
  | { type: "paragraph"; index?: number; text: string; translation_state?: TranslationState }
  | { type: "illustration"; scene_index: number };

export interface Run {
  id: string;
  session_id: string;
  status: RunStatus;
  source_language: string;
  language: string;
  topic_short: string;
  story_title: string;
  story_title_translation_state?: TranslationState;
  story_topic_description: string;
  story_topic_description_translation_state?: TranslationState;
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

export interface Companion {
  description: string;
  interaction: string;
}

export interface Illustration {
  id: string;
  scene_index: number;
  scene_excerpt: string;
  scene_excerpt_translation_state?: TranslationState;
  paragraph_index: number;
  character_role: CharacterRole | null;
  current_workflow: string | null;
  current_concept: string;
  current_concept_translation_state?: TranslationState;
  state: IllustrationState;
  concept_attempt: number;
  prompt_attempt: number;
  image_url: string | null;
  companion: Companion | null;
  manual_attempts?: number;
  manual_session?: ManualSessionSummary | null;
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
  current_concept: string;
  scene_excerpt: string;
}

export interface ParagraphUpdatedEvent {
  paragraph_index: number;
  text: string;
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

export interface IllustrationCompanionUpdatedEvent {
  illustration_id: string;
  scene_index: number;
  companion: Companion | null;
}

export interface IllustrationRoleUpdatedEvent {
  illustration_id: string;
  scene_index: number;
  character_role: CharacterRole | null;
}

export interface TranslationItem {
  kind:
    | "story_title"
    | "story_topic_description"
    | "paragraph"
    | "illustration_concept"
    | "scene_excerpt";
  paragraph_index?: number;
  scene_index?: number;
  text: string;
  source_hash: string;
}

export interface TranslationsRefreshedEvent {
  language: string;
  items: TranslationItem[];
}

export interface RunCompletedEvent {
  completed: number;
  failed: number;
}

export interface RunFailedEvent {
  error_code: string;
  error_message: string;
}

// ── § 6A manual chat SSE events ───────────────────────────────────────────

export interface IllustrationManualStartedEvent {
  illustration_id: string;
  scene_index: number;
  sub_phase: ManualSubPhase;
  welcome_message: {
    id: string;
    role: ManualMessageRole;
    content: string;
    created_at: string;
  };
}

export interface ManualMessageAppendedEvent {
  illustration_id: string;
  scene_index: number;
  sub_phase: ManualSubPhase;
  message: ManualMessage;
}

export interface ManualImageRenderedEvent {
  illustration_id: string;
  scene_index: number;
  sub_phase: ManualSubPhase;
  manual_attempt: number;
  image_url: string;
  image_message_id: string;
  // § 6A.10: per-attempt provenance for the new image row. Used by the
  // frontend to render ManualImageCard popovers.
  concept_used: string | null;
  positive_prompt: string | null;
  negative_prompt: string | null;
}

export interface IllustrationManualEndedEvent {
  illustration_id: string;
  scene_index: number;
  outcome: "completed" | "exhausted" | "cancelled";
}

export type SseEvent =
  | { type: "snapshot"; data: SnapshotEvent }
  | { type: "illustration_state"; data: IllustrationStateEvent }
  | { type: "illustration_completed"; data: IllustrationCompletedEvent }
  | { type: "illustration_failed"; data: IllustrationFailedEvent }
  | { type: "illustration_companion_updated"; data: IllustrationCompanionUpdatedEvent }
  | { type: "illustration_role_updated"; data: IllustrationRoleUpdatedEvent }
  | { type: "illustration_manual_started"; data: IllustrationManualStartedEvent }
  | { type: "manual_message_appended"; data: ManualMessageAppendedEvent }
  | { type: "manual_image_rendered"; data: ManualImageRenderedEvent }
  | { type: "illustration_manual_ended"; data: IllustrationManualEndedEvent }
  | { type: "translations_refreshed"; data: TranslationsRefreshedEvent }
  | { type: "paragraph_updated"; data: ParagraphUpdatedEvent }
  | { type: "run_completed"; data: RunCompletedEvent }
  | { type: "run_failed"; data: RunFailedEvent }
  | { type: "run_cancelled"; data: Record<string, never> }
  | { type: "heartbeat"; data: Record<string, never> };
