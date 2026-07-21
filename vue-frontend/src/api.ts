import type {
  ChatHistory,
  ChatMessage,
  FeedbackPayload,
  RagDocument,
  ServiceMetadata,
  StreamEvent
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";

export async function getInfo(): Promise<ServiceMetadata> {
  const response = await fetch(`${API_BASE_URL}/info`);
  if (!response.ok) {
    throw new Error(`Failed to load service info: ${response.status}`);
  }
  return (await response.json()) as ServiceMetadata;
}

export async function getHistory(threadId: string): Promise<ChatHistory> {
  const response = await fetch(`${API_BASE_URL}/history`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ thread_id: threadId })
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
  const response = await fetch(`${API_BASE_URL}/${encodeURIComponent(payload.agent)}/invoke`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      message: payload.message,
      model: payload.model,
      thread_id: payload.threadId,
      user_id: payload.userId
    })
  });
  if (!response.ok) {
    throw new Error(`Agent invoke failed: ${response.status}`);
  }
  return (await response.json()) as ChatMessage;
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
  const response = await fetch(`${API_BASE_URL}/${encodeURIComponent(payload.agent)}/stream`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      message: payload.message,
      model: payload.model,
      thread_id: payload.threadId,
      user_id: payload.userId,
      stream_tokens: payload.streamTokens
    })
  });

  if (!response.ok || !response.body) {
    throw new Error(`Agent stream failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const rawEvent of events) {
      const parsed = parseSseEvent(rawEvent);
      if (parsed === "done") {
        return;
      }
      if (parsed) {
        onEvent(parsed);
      }
    }
  }
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
  const response = await fetch(`${API_BASE_URL}/rag/documents`);
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
    method: "DELETE"
  });
  if (!response.ok) {
    throw new Error(`Document deletion failed: ${response.status}`);
  }
}

function parseSseEvent(rawEvent: string): StreamEvent | "done" | null {
  const dataLine = rawEvent
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line.startsWith("data: "));
  if (!dataLine) {
    return null;
  }

  const data = dataLine.slice("data: ".length);
  if (data === "[DONE]") {
    return "done";
  }
  return JSON.parse(data) as StreamEvent;
}

function jsonHeaders(): HeadersInit {
  return {
    "Content-Type": "application/json"
  };
}
