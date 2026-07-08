<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-title">🧰 Agent Service Toolkit</div>
        <p>Full toolkit for running an AI agent service built with LangGraph, FastAPI and Streamlit</p>
      </div>

      <button class="sidebar-button" type="button" @click="newChat">▣ New Chat</button>

      <section class="sidebar-section">
        <button class="sidebar-button" type="button" @click="settingsOpen = !settingsOpen">
          ⚙ Settings⌄
        </button>
        <div v-if="settingsOpen" class="settings-panel">
          <label>
            <span>LLM to use</span>
            <select v-model="selectedModel">
              <option v-for="model in metadata?.models ?? []" :key="model" :value="model">
                {{ model }}
              </option>
            </select>
          </label>
          <label>
            <span>Agent to use</span>
            <select v-model="selectedAgent">
              <option v-for="agent in metadata?.agents ?? []" :key="agent.key" :value="agent.key">
                {{ agent.key }}
              </option>
            </select>
          </label>
          <label class="toggle-row">
            <input v-model="useStreaming" type="checkbox" />
            <span>Stream results</span>
          </label>
          <label>
            <span>User ID</span>
            <input :value="userId" disabled />
          </label>
        </div>
      </section>

      <button class="sidebar-button" type="button" @click="architectureOpen = true">
        ⌘ Architecture
      </button>
      <button class="sidebar-button" type="button" @click="privacyOpen = !privacyOpen">
        @ Privacy⌄
      </button>
      <div v-if="privacyOpen" class="side-note">
        Prompts, responses and feedback can be recorded by the service for evaluation when tracing is
        enabled.
      </div>
      <button class="sidebar-button" type="button" @click="shareOpen = true">↥ Share/resume chat</button>

      <a class="source-link" href="https://github.com/JoshuaC215/agent-service-toolkit" target="_blank">
        View the source code
      </a>
      <p class="made-with">Made with ♡ by Joshua in Oakland</p>
    </aside>

    <main class="chat-page">
      <div v-if="error" class="error-card">
        {{ error }}
      </div>

      <div class="chat-list">
        <div v-if="messages.length === 0" class="message-row ai">
          <div class="avatar ai-avatar">🤖</div>
          <div class="message-content">{{ welcomeMessage }}</div>
        </div>

        <template v-for="item in renderItems" :key="item.id">
          <div v-if="item.kind === 'message'" class="message-row" :class="item.message.type">
            <div class="avatar" :class="`${item.message.type}-avatar`">
              {{ avatarFor(item.message.type) }}
            </div>
            <div class="message-stack">
              <div v-if="item.message.content" class="message-content">
                {{ item.message.content }}
              </div>
              <div v-if="item.message.tool_calls.length" class="tool-list">
                <details
                  v-for="toolCall in item.message.tool_calls"
                  :key="toolCall.id ?? toolCall.name"
                  class="tool-card"
                  open
                >
                  <summary>
                    {{ toolCall.name.includes("transfer_to") ? "💼 Sub Agent" : "🛠️ Tool Call" }}:
                    {{ toolCall.name }}
                  </summary>
                  <pre>Input:
{{ formatJson(toolCall.args) }}</pre>
                  <pre v-if="toolResults[toolCall.id ?? '']">Output:
{{ toolResults[toolCall.id ?? ""] }}</pre>
                </details>
              </div>
            </div>
          </div>

          <div v-else class="message-row task">
            <div class="avatar task-avatar">🏭</div>
            <div class="task-card">
              <div class="task-title">{{ taskLabel(item.task) }}</div>
              <pre>{{ formatJson(item.task.data) }}</pre>
            </div>
          </div>
        </template>

        <div v-if="streamingText" class="message-row ai">
          <div class="avatar ai-avatar">🤖</div>
          <div class="message-content">{{ streamingText }}</div>
        </div>

        <div v-if="latestAiRunId" class="feedback-row">
          <button
            v-for="star in 5"
            :key="star"
            class="star-button"
            :class="{ active: selectedFeedback >= star }"
            type="button"
            @click="recordFeedback(star)"
          >
            ☆
          </button>
          <span v-if="feedbackStatus">{{ feedbackStatus }}</span>
        </div>
      </div>

      <form class="chat-input" @submit.prevent="submitMessage">
        <input
          v-model.trim="draft"
          :disabled="loading || !metadata"
          autocomplete="off"
          placeholder="Ask anything"
        />
        <button type="submit" :disabled="loading || !draft || !metadata">Send</button>
      </form>
    </main>

    <div v-if="architectureOpen" class="modal-backdrop" @click.self="architectureOpen = false">
      <div class="modal architecture-modal">
        <button class="modal-close" type="button" @click="architectureOpen = false">×</button>
        <h2>Architecture</h2>
        <img src="/agent_architecture.png" alt="Agent architecture" />
      </div>
    </div>

    <div v-if="shareOpen" class="modal-backdrop" @click.self="shareOpen = false">
      <div class="modal">
        <button class="modal-close" type="button" @click="shareOpen = false">×</button>
        <h2>Share/resume chat</h2>
        <p>Chat URL:</p>
        <pre>{{ shareUrl }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { getHistory, getInfo, invokeAgent, sendFeedback, streamAgent } from "./api";
import type { ChatMessage, ChatMessageType, ServiceMetadata, TaskData } from "./types";

type RenderItem =
  | { id: string; kind: "message"; message: ChatMessage }
  | { id: string; kind: "task"; task: TaskData };

const metadata = ref<ServiceMetadata | null>(null);
const selectedAgent = ref("");
const selectedModel = ref("");
const useStreaming = ref(true);
const settingsOpen = ref(false);
const privacyOpen = ref(false);
const architectureOpen = ref(false);
const shareOpen = ref(false);
const messages = ref<ChatMessage[]>([]);
const renderItems = ref<RenderItem[]>([]);
const toolResults = ref<Record<string, string>>({});
const draft = ref("");
const loading = ref(false);
const error = ref("");
const streamingText = ref("");
const selectedFeedback = ref(0);
const feedbackStatus = ref("");

const userId = getOrCreateQueryParam("user_id");
const threadId = ref(getOrCreateQueryParam("thread_id"));

const latestAiRunId = computed(() => {
  const latest = [...messages.value].reverse().find((message) => message.type === "ai" && message.run_id);
  return latest?.run_id ?? "";
});

const shareUrl = computed(() => {
  const url = new URL(window.location.href);
  url.searchParams.set("thread_id", threadId.value);
  url.searchParams.set("user_id", userId);
  return url.toString();
});

const welcomeMessage = computed(() => {
  switch (selectedAgent.value) {
    case "chatbot":
      return "Hello! I'm a simple chatbot. Ask me anything!";
    case "interrupt-agent":
      return "Hello! I'm an interrupt agent. Tell me your birthday and I will predict your personality!";
    case "research-assistant":
      return "Hello! I'm an AI-powered research assistant with web search and a calculator. Ask me anything!";
    case "rag-assistant":
      return "Hello! I'm an AI-powered Company Policy & HR assistant with access to AcmeTech's Employee Handbook. I can help you find information about benefits, remote work, time-off policies, company values, and more. Ask me anything!";
    default:
      return "Hello! I'm an AI agent. Ask me anything!";
  }
});

onMounted(async () => {
  try {
    metadata.value = await getInfo();
    selectedAgent.value = metadata.value.default_agent;
    selectedModel.value = metadata.value.default_model;
    if (new URL(window.location.href).searchParams.has("thread_id")) {
      await loadHistory();
    }
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Error connecting to agent service.";
  }
});

async function submitMessage(): Promise<void> {
  if (!draft.value || !metadata.value || loading.value) {
    return;
  }

  const content = draft.value;
  draft.value = "";
  error.value = "";
  loading.value = true;
  streamingText.value = "";
  selectedFeedback.value = 0;
  feedbackStatus.value = "";

  const humanMessage = createMessage("human", content);
  appendMessage(humanMessage);

  try {
    if (useStreaming.value) {
      await streamAgent(
        {
          agent: selectedAgent.value,
          message: content,
          model: selectedModel.value,
          threadId: threadId.value,
          userId,
          streamTokens: true
        },
        (event) => {
          if (event.type === "token") {
            streamingText.value += event.content;
            return;
          }
          if (event.type === "error") {
            error.value = event.content;
            return;
          }
          if (streamingText.value) {
            streamingText.value = "";
          }
          appendMessage(event.content);
        }
      );
    } else {
      const response = await invokeAgent({
        agent: selectedAgent.value,
        message: content,
        model: selectedModel.value,
        threadId: threadId.value,
        userId
      });
      appendMessage(response);
    }
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Error generating response.";
  } finally {
    loading.value = false;
  }
}

function appendMessage(message: ChatMessage): void {
  messages.value.push(message);
  if (message.type === "tool" && message.tool_call_id) {
    toolResults.value[message.tool_call_id] = message.content;
    return;
  }
  if (message.type === "custom") {
    renderItems.value.push({
      id: `${renderItems.value.length}-task-${message.run_id ?? crypto.randomUUID()}`,
      kind: "task",
      task: message.custom_data as unknown as TaskData
    });
    return;
  }
  renderItems.value.push({
    id: `${renderItems.value.length}-message-${message.run_id ?? crypto.randomUUID()}`,
    kind: "message",
    message
  });
}

async function loadHistory(): Promise<void> {
  try {
    const history = await getHistory(threadId.value);
    messages.value = [];
    renderItems.value = [];
    toolResults.value = {};
    for (const message of history.messages) {
      appendMessage(message);
    }
  } catch {
    error.value = "No message history found for this Thread ID.";
  }
}

function newChat(): void {
  messages.value = [];
  renderItems.value = [];
  toolResults.value = {};
  streamingText.value = "";
  selectedFeedback.value = 0;
  feedbackStatus.value = "";
  threadId.value = crypto.randomUUID();
  const url = new URL(window.location.href);
  url.searchParams.set("thread_id", threadId.value);
  url.searchParams.set("user_id", userId);
  window.history.replaceState({}, "", url.toString());
}

async function recordFeedback(star: number): Promise<void> {
  if (!latestAiRunId.value) {
    return;
  }
  selectedFeedback.value = star;
  feedbackStatus.value = "";
  try {
    await sendFeedback({
      run_id: latestAiRunId.value,
      key: "human-feedback-stars",
      score: star / 5,
      kwargs: { comment: "In-line human feedback" }
    });
    feedbackStatus.value = "Feedback recorded";
  } catch (caught) {
    feedbackStatus.value = caught instanceof Error ? caught.message : "Feedback failed";
  }
}

function createMessage(type: ChatMessageType, content: string): ChatMessage {
  return {
    type,
    content,
    tool_calls: [],
    tool_call_id: null,
    run_id: null,
    response_metadata: {},
    custom_data: {}
  };
}

function getOrCreateQueryParam(name: string): string {
  const url = new URL(window.location.href);
  const existing = url.searchParams.get(name);
  if (existing) {
    return existing;
  }
  const value = crypto.randomUUID();
  url.searchParams.set(name, value);
  window.history.replaceState({}, "", url.toString());
  return value;
}

function avatarFor(type: ChatMessageType): string {
  if (type === "human") return "👤";
  if (type === "ai") return "🤖";
  if (type === "tool") return "🛠️";
  return "🏭";
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function taskLabel(task: TaskData): string {
  if (task.state === "complete" && task.result === "error") {
    return `Task ${task.name ?? ""} ended with error. Output:`;
  }
  if (task.state === "complete") {
    return `Task ${task.name ?? ""} completed successfully. Output:`;
  }
  if (task.state === "running") {
    return `Task ${task.name ?? ""} wrote:`;
  }
  return `Task ${task.name ?? ""} has started. Input:`;
}
</script>
