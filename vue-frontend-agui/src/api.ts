import { HttpAgent } from "@ag-ui/client";
import type { Message } from "@ag-ui/core";

import type {
  AuthResponse,
  ChatHistory,
  ChatMessage,
  Conversation,
  FeedbackPayload,
  RagDocument,
  ServiceMetadata,
  StreamEvent,
  UserProfile
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";
const TOKEN_STORAGE_KEY = "agent-service-access-token";

export function getAccessToken(): string {
  return localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
}

export function setAccessToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearAccessToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export async function registerUser(payload: {
  email: string;
  displayName: string;
  password: string;
}): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/register", {
    method: "POST",
    headers: jsonHeaders(false),
    body: JSON.stringify({
      email: payload.email,
      display_name: payload.displayName,
      password: payload.password
    })
  });
}

export async function loginUser(email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/login", {
    method: "POST",
    headers: jsonHeaders(false),
    body: JSON.stringify({ email, password })
  });
}

export async function getCurrentUser(): Promise<UserProfile> {
  return request<UserProfile>("/auth/me", { headers: authHeaders() });
}

export async function logoutUser(): Promise<void> {
  await request<void>("/auth/logout", { method: "POST", headers: authHeaders() });
}

export async function listConversations(): Promise<Conversation[]> {
  return request<Conversation[]>("/conversations", { headers: authHeaders() });
}

export async function getInfo(): Promise<ServiceMetadata> {
  const response = await fetch(`${API_BASE_URL}/info`, { headers: authHeaders() });
  if (!response.ok) {
    throw new Error(`Failed to load service info: ${response.status}`);
  }
  return (await response.json()) as ServiceMetadata;
}

export async function getHistory(threadId: string): Promise<ChatHistory> {
  const response = await fetch(`${API_BASE_URL}/conversations/${encodeURIComponent(threadId)}/messages`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw new Error(`Failed to load chat history: ${response.status}`);
  }
  return (await response.json()) as ChatHistory;
}

export async function invokeAgent(payload: {
  agent: string;
  message: string;
  model: string;
  threadId: string;
  userId: string;
}): Promise<ChatMessage> {
  const messages = await runAgentOverAgui(payload);
  const response = [...messages].reverse().find((message) => message.type === "ai") ?? messages.at(-1);
  if (!response) {
    throw new Error("AG-UI run completed without a response message");
  }
  return response;
}

export async function streamAgent(
  payload: {
    agent: string;
    message: string;
    model: string;
    threadId: string;
    userId: string;
    streamTokens: boolean;
  },
  onEvent: (event: StreamEvent) => void
): Promise<void> {
  const messages = await runAgentOverAgui(payload, onEvent);
  for (const message of messages) {
    onEvent({ type: "message", content: message });
  }
}

interface AguiRunPayload {
  agent: string;
  message: string;
  model: string;
  threadId: string;
  userId: string;
  streamTokens?: boolean;
}

async function runAgentOverAgui(
  payload: AguiRunPayload,
  onEvent?: (event: StreamEvent) => void
): Promise<ChatMessage[]> {
  const runId = crypto.randomUUID();
  const token = getAccessToken();
  const agent = new HttpAgent({
    url: `${API_BASE_URL}/agui/${encodeURIComponent(payload.agent)}/run`,
    threadId: payload.threadId,
    headers: token ? { Authorization: `Bearer ${token}` } : {}
  });

  agent.messages = [
    {
      id: crypto.randomUUID(),
      role: "user",
      content: payload.message
    }
  ];

  const currentRunMessages: ChatMessage[] = [];
  const messageIndexes = new Map<string, number>();
  const upsertCurrentMessage = (message: Message): void => {
    const converted = aguiMessageToChatMessage(message, runId);
    if (!converted) {
      return;
    }
    const existingIndex = messageIndexes.get(message.id);
    if (existingIndex === undefined) {
      messageIndexes.set(message.id, currentRunMessages.length);
      currentRunMessages.push(converted);
    } else {
      currentRunMessages[existingIndex] = converted;
    }
  };
  let protocolError: string | null = null;
  await agent.runAgent(
    {
      runId,
      forwardedProps: {
        configurable: {
          model: payload.model,
          user_id: payload.userId
        }
      }
    },
    {
      onTextMessageContentEvent({ event }) {
        if (payload.streamTokens) {
          onEvent?.({ type: "token", content: event.delta });
        }
      },
      onRunErrorEvent({ event }) {
        protocolError = event.message;
        onEvent?.({ type: "error", content: event.message });
      },
      onNewMessage({ message }) {
        upsertCurrentMessage(message);
      },
      onNewToolCall({ toolCall, messages }) {
        const parentMessage = messages.find(
          (message) =>
            message.role === "assistant" &&
            message.toolCalls?.some((candidate) => candidate.id === toolCall.id)
        );
        if (parentMessage) {
          upsertCurrentMessage(parentMessage);
        }
      },
      onCustomEvent({ event }) {
        if (event.name === "on_interrupt") {
          currentRunMessages.push(
            createChatMessage(
              "ai",
              typeof event.value === "string" ? event.value : JSON.stringify(event.value, null, 2),
              runId
            )
          );
          return;
        }
        currentRunMessages.push({
          ...createChatMessage("custom", "", runId),
          custom_data: extractCustomData(event.name, event.value, runId)
        });
      }
    }
  );

  if (protocolError) {
    throw new Error(protocolError);
  }

  return currentRunMessages;
}

function aguiMessageToChatMessage(message: Message, runId: string): ChatMessage | null {
  if (message.role === "assistant") {
    return {
      ...createChatMessage("ai", message.content ?? "", runId),
      tool_calls: (message.toolCalls ?? []).map((toolCall) => ({
        name: toolCall.function.name,
        args: parseToolArguments(toolCall.function.arguments),
        id: toolCall.id,
        type: "tool_call"
      })),
      response_metadata: { agui_message_id: message.id }
    };
  }

  if (message.role === "tool") {
    return {
      ...createChatMessage("tool", message.content, runId),
      tool_call_id: message.toolCallId,
      response_metadata: {
        agui_message_id: message.id,
        ...(message.error ? { error: message.error } : {})
      }
    };
  }

  return null;
}

function createChatMessage(type: ChatMessage["type"], content: string, runId: string): ChatMessage {
  return {
    type,
    content,
    tool_calls: [],
    tool_call_id: null,
    run_id: runId,
    response_metadata: {},
    custom_data: {}
  };
}

function parseToolArguments(value: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return { value: parsed };
  } catch {
    return { raw: value };
  }
}

function extractCustomData(
  eventName: string,
  value: unknown,
  runId: string
): Record<string, unknown> {
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    if (Array.isArray(record.content) && isRecord(record.content[0])) {
      return record.content[0];
    }
    if (isRecord(record.data)) {
      return record.data;
    }
    return record;
  }
  return {
    name: eventName,
    run_id: runId,
    state: null,
    result: null,
    data: { value }
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function sendFeedback(payload: FeedbackPayload): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/feedback`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Feedback failed: ${response.status}`);
  }
}

export async function listRagDocuments(): Promise<RagDocument[]> {
  const response = await fetch(`${API_BASE_URL}/rag/documents`, { headers: authHeaders() });

  if (!response.ok) {
    throw new Error(`Failed to load RAG documents: ${response.status}`);
  }
  return (await response.json()) as RagDocument[];
}

export async function uploadRagDocument(file: File): Promise<RagDocument> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`${API_BASE_URL}/rag/documents`, {
    method: "POST",
    headers: authHeaders(),
    body
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail || `Document upload failed: ${response.status}`);
  }
  return (await response.json()) as RagDocument;
}

export async function deleteRagDocument(documentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/rag/documents/${encodeURIComponent(documentId)}`, {
    method: "DELETE",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw new Error(`Document deletion failed: ${response.status}`);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function authHeaders(): HeadersInit {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function jsonHeaders(includeAuth = true): HeadersInit {
  return {
    ...(includeAuth ? authHeaders() : {}),
    "Content-Type": "application/json"
  };
}
