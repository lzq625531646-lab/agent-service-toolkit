export interface AgentInfo {
  key: string;
  description: string;
}

export interface ServiceMetadata {
  agents: AgentInfo[];
  models: string[];
  default_agent: string;
  default_model: string;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  id: string | null;
  type?: "tool_call";
}

export type ChatMessageType = "human" | "ai" | "tool" | "custom";

export interface ChatMessage {
  type: ChatMessageType;
  content: string;
  tool_calls: ToolCall[];
  tool_call_id: string | null;
  run_id: string | null;
  response_metadata: Record<string, unknown>;
  custom_data: Record<string, unknown>;
}

export interface StreamEventMessage {
  type: "message";
  content: ChatMessage;
}

export interface StreamEventToken {
  type: "token";
  content: string;
}

export interface StreamEventError {
  type: "error";
  content: string;
}

export type StreamEvent = StreamEventMessage | StreamEventToken | StreamEventError;

export interface ChatHistory {
  messages: ChatMessage[];
}

export interface TaskData {
  name?: string | null;
  run_id: string;
  state?: "new" | "running" | "complete" | null;
  result?: "success" | "error" | null;
  data: Record<string, unknown>;
}

export interface FeedbackPayload {
  run_id: string;
  key: string;
  score: number;
  kwargs: Record<string, unknown>;
}

export interface RagDocument {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  chunk_count: number;
  created_at: string;
}
