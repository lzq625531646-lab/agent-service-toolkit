<template>
  <div v-if="authLoading" class="grid min-h-screen place-items-center bg-slate-950 text-lg font-semibold text-white">
    Loading workspace…
  </div>
  <AuthScreen v-else-if="!currentUser" @authenticated="handleAuthenticated" />
  <div
    v-else
    class="grid min-h-screen grid-cols-1 bg-white text-[#31333f] min-[901px]:grid-cols-[21rem_minmax(0,1fr)]"
  >
    <aside class="flex flex-col gap-3.5 bg-slate-100 px-4 py-4 min-[901px]:min-h-screen min-[901px]:pt-24">
      <div>
        <div class="mb-6 text-xl font-bold text-slate-800">🧰 Agent Service Toolkit</div>
        <p class="text-[0.98rem] leading-7 text-slate-600">
          Full toolkit for running an AI agent service built with LangGraph, FastAPI and Streamlit
        </p>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-3">
        <div class="font-bold text-slate-900">{{ currentUser.display_name }}</div>
        <div class="truncate text-xs text-slate-500">{{ currentUser.email }}</div>
        <button class="mt-2 text-xs font-bold text-red-600 hover:underline" type="button" @click="signOut">
          Sign out
        </button>
      </div>

      <button :class="sidebarButtonClass" type="button" @click="newChat">▣ New Chat</button>

      <section class="min-h-0">
        <div class="mb-2 flex items-center justify-between px-1">
          <span class="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">History</span>
          <button class="border-0 bg-transparent text-xs font-bold text-slate-500 hover:text-slate-900" type="button" @click="refreshConversations">
            Refresh
          </button>
        </div>
        <div class="grid max-h-56 gap-1.5 overflow-y-auto pr-1">
          <button
            v-for="conversation in conversations"
            :key="conversation.thread_id"
            class="rounded-lg border px-3 py-2.5 text-left transition"
            :class="conversation.thread_id === threadId ? 'border-red-300 bg-red-50' : 'border-transparent bg-white/70 hover:border-slate-300 hover:bg-white'"
            type="button"
            @click="selectConversation(conversation)"
          >
            <span class="block truncate text-sm font-semibold text-slate-800">{{ conversation.title }}</span>
            <span class="mt-1 block truncate text-xs text-slate-500">
              {{ conversation.agent_id }} · {{ formatConversationDate(conversation.updated_at) }}
            </span>
          </button>
          <p v-if="!conversations.length" class="m-0 rounded-lg bg-white/60 px-3 py-3 text-sm text-slate-500">
            No saved conversations yet.
          </p>
        </div>
      </section>
      <button :class="sidebarButtonClass" type="button" @click="activeView = 'documents'">
        ▤ RAG Documents
      </button>

      <section>
        <button :class="sidebarButtonClass" type="button" @click="settingsOpen = !settingsOpen">
          ⚙ Settings⌄
        </button>
        <div v-if="settingsOpen" class="mt-2 grid gap-3 rounded-lg border border-slate-300 bg-white p-3">
          <label :class="fieldClass">
            <span :class="fieldLabelClass">LLM to use</span>
            <select v-model="selectedModel" :class="fieldControlClass">
              <option v-for="model in metadata?.models ?? []" :key="model" :value="model">
                {{ model }}
              </option>
            </select>
          </label>
          <label :class="fieldClass">
            <span :class="fieldLabelClass">Agent to use</span>
            <select v-model="selectedAgent" :class="fieldControlClass">
              <option v-for="agent in metadata?.agents ?? []" :key="agent.key" :value="agent.key">
                {{ agent.key }}
              </option>
            </select>
          </label>
          <label class="flex items-center gap-2">
            <input v-model="useStreaming" class="size-4 rounded border-slate-300 accent-[#ff4b4b]" type="checkbox" />
            <span :class="fieldLabelClass">Stream results</span>
          </label>
          <label :class="fieldClass">
            <span :class="fieldLabelClass">Account ID</span>
            <input :value="currentUser.id" :class="fieldControlClass" disabled />
          </label>
        </div>
      </section>

      <button :class="sidebarButtonClass" type="button" @click="architectureOpen = true">
        ⌘ Architecture
      </button>
      <button :class="sidebarButtonClass" type="button" @click="privacyOpen = !privacyOpen">
        @ Privacy⌄
      </button>
      <div v-if="privacyOpen" class="rounded-lg bg-white/70 px-3 py-2 text-[0.98rem] leading-7 text-slate-600">
        Prompts, responses and feedback can be recorded by the service for evaluation when tracing is
        enabled.
      </div>
      <button :class="sidebarButtonClass" type="button" @click="shareOpen = true">↥ Share/resume chat</button>

      <a
        class="mt-auto text-sm font-semibold text-sky-700 underline-offset-4 hover:underline"
        href="https://github.com/JoshuaC215/agent-service-toolkit"
        target="_blank"
      >
        View the source code
      </a>
      <p class="m-0 text-sm text-slate-500">Made with ♡ by Joshua in Oakland</p>
    </aside>

    <main v-if="activeView === 'chat'" class="relative flex min-w-0 flex-col items-center px-4 pb-28 pt-8 min-[901px]:px-8 min-[901px]:pb-[7.5rem] min-[901px]:pt-[6.8rem]">
      <div v-if="error" class="mb-5 w-full max-w-[820px] rounded-lg bg-red-50 px-4 py-4 font-semibold text-red-600">
        {{ error }}
      </div>

      <div class="w-full max-w-[820px]">
        <div v-if="messages.length === 0" class="mb-6 grid grid-cols-[42px_minmax(0,1fr)] gap-3">
          <div :class="avatarClasses('ai')">🤖</div>
          <div :class="messageContentClasses('ai')">{{ welcomeMessage }}</div>
        </div>

        <template v-for="item in renderItems" :key="item.id">
          <div v-if="item.kind === 'message'" class="mb-6 grid grid-cols-[42px_minmax(0,1fr)] gap-3">
            <div :class="avatarClasses(item.message.type)">
              {{ avatarFor(item.message.type) }}
            </div>
            <div class="grid min-w-0 gap-3">
              <div v-if="item.message.content" :class="messageContentClasses(item.message.type)">
                {{ item.message.content }}
              </div>
              <div v-if="item.message.tool_calls.length" class="grid gap-2.5">
                <details
                  v-for="toolCall in item.message.tool_calls"
                  :key="toolCall.id ?? toolCall.name"
                  class="overflow-hidden rounded-lg border border-slate-300 bg-white"
                  open
                >
                  <summary class="cursor-pointer px-3.5 py-3 font-bold text-slate-800">
                    {{ toolCall.name.includes("transfer_to") ? "💼 Sub Agent" : "🛠️ Tool Call" }}:
                    {{ toolCall.name }}
                  </summary>
                  <pre :class="preClass">Input:
{{ formatJson(toolCall.args) }}</pre>
                  <pre v-if="toolResults[toolCall.id ?? '']" :class="preClass">Output:
{{ toolResults[toolCall.id ?? ""] }}</pre>
                </details>
              </div>
            </div>
          </div>

          <div v-else class="mb-6 grid grid-cols-[42px_minmax(0,1fr)] gap-3">
            <div :class="avatarClasses('task')">🏭</div>
            <div class="overflow-hidden rounded-lg border border-slate-300 bg-white">
              <div class="px-3.5 py-3 font-bold text-slate-800">{{ taskLabel(item.task) }}</div>
              <pre :class="preClass">{{ formatJson(item.task.data) }}</pre>
            </div>
          </div>
        </template>

        <div v-if="streamingText" class="mb-6 grid grid-cols-[42px_minmax(0,1fr)] gap-3">
          <div :class="avatarClasses('ai')">🤖</div>
          <div :class="messageContentClasses('ai')">{{ streamingText }}</div>
        </div>

        <div v-if="latestAiRunId" class="ml-[54px] flex items-center gap-1.5 text-sm text-slate-500">
          <button
            v-for="star in 5"
            :key="star"
            class="border-0 bg-transparent text-xl transition"
            :class="selectedFeedback >= star ? 'text-amber-500' : 'text-slate-400 hover:text-amber-500'"
            type="button"
            @click="recordFeedback(star)"
          >
            ☆
          </button>
          <span v-if="feedbackStatus">{{ feedbackStatus }}</span>
        </div>
      </div>

      <form
        class="sticky bottom-4 mx-auto grid w-full max-w-[820px] grid-cols-[minmax(0,1fr)_auto] gap-2.5 rounded-xl border border-slate-300 bg-white p-2.5 shadow-[0_12px_32px_rgba(31,41,55,0.1)] min-[901px]:fixed min-[901px]:bottom-[1.6rem] min-[901px]:left-[calc(21rem+2rem)] min-[901px]:right-8 min-[901px]:w-auto"
        @submit.prevent="submitMessage"
      >
        <input
          v-model.trim="draft"
          :disabled="loading || !metadata"
          class="min-h-[42px] min-w-0 border-0 px-2 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:opacity-60"
          autocomplete="off"
          placeholder="Ask anything"
        />
        <button
          class="min-h-[42px] min-w-[76px] rounded-lg bg-[#ff4b4b] px-4 font-bold text-white transition hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-60"
          type="submit"
          :disabled="loading || !draft || !metadata"
        >
          Send
        </button>
      </form>
    </main>

    <RagDocuments v-else @back="activeView = 'chat'" />

    <div v-if="architectureOpen" class="fixed inset-0 z-50 grid place-items-center bg-slate-900/35 p-6" @click.self="architectureOpen = false">
      <div :class="modalClass">
        <button :class="modalCloseClass" type="button" aria-label="Close architecture modal" @click="architectureOpen = false">×</button>
        <h2 class="mb-4 text-2xl font-bold text-slate-900">Architecture</h2>
        <img class="w-full rounded-lg border border-slate-300" src="/agent_architecture.png" alt="Agent architecture" />
      </div>
    </div>

    <div v-if="shareOpen" class="fixed inset-0 z-50 grid place-items-center bg-slate-900/35 p-6" @click.self="shareOpen = false">
      <div :class="modalClass">
        <button :class="modalCloseClass" type="button" aria-label="Close share modal" @click="shareOpen = false">×</button>
        <h2 class="mb-4 text-2xl font-bold text-slate-900">Share/resume chat</h2>
        <p class="mb-2 text-slate-700">Chat URL:</p>
        <pre class="overflow-auto rounded-lg border border-slate-300 bg-slate-50 p-3 text-sm leading-6 text-slate-700">{{ shareUrl }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import {
  clearAccessToken,
  getAccessToken,
  getCurrentUser,
  getHistory,
  getInfo,
  invokeAgent,
  listConversations,
  logoutUser,
  sendFeedback,
  streamAgent
} from "./api";
import AuthScreen from "./AuthScreen.vue";
import RagDocuments from "./RagDocuments.vue";
import type {
  AuthResponse,
  ChatMessage,
  ChatMessageType,
  Conversation,
  ServiceMetadata,
  TaskData,
  UserProfile
} from "./types";

type RenderItem =
  | { id: string; kind: "message"; message: ChatMessage }
  | { id: string; kind: "task"; task: TaskData };

const metadata = ref<ServiceMetadata | null>(null);
const authLoading = ref(true);
const currentUser = ref<UserProfile | null>(null);
const conversations = ref<Conversation[]>([]);
const activeView = ref<"chat" | "documents">("chat");
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

const threadId = ref(getQueryParam("thread_id") || crypto.randomUUID());

const sidebarButtonClass =
  "min-h-[46px] w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-800 transition hover:border-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60";
const fieldClass = "grid gap-1.5";
const fieldLabelClass = "text-[0.82rem] font-semibold text-slate-500";
const fieldControlClass =
  "min-h-[38px] w-full rounded-md border border-slate-300 bg-white px-2.5 text-sm text-slate-900 outline-none focus:border-red-400 focus:ring-2 focus:ring-red-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500";
const preClass =
  "m-0 overflow-auto border-t border-slate-300 bg-slate-50 px-3.5 py-3 text-[0.85rem] leading-6 text-slate-700";
const modalClass =
  "relative max-h-[88vh] w-full max-w-[720px] overflow-auto rounded-lg bg-white p-6 shadow-[0_24px_80px_rgba(17,24,39,0.2)]";
const modalCloseClass =
  "absolute right-3 top-3 grid size-[34px] place-items-center rounded-full border-0 bg-slate-100 text-2xl leading-none text-slate-700 transition hover:bg-slate-200";

const latestAiRunId = computed(() => {
  const latest = [...messages.value].reverse().find((message) => message.type === "ai" && message.run_id);
  return latest?.run_id ?? "";
});

const shareUrl = computed(() => {
  const url = new URL(window.location.href);
  url.searchParams.set("thread_id", threadId.value);
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
  if (!getAccessToken()) {
    authLoading.value = false;
    return;
  }
  try {
    currentUser.value = await getCurrentUser();
    await initializeWorkspace();
  } catch (caught) {
    clearAccessToken();
    currentUser.value = null;
  } finally {
    authLoading.value = false;
  }
});

async function handleAuthenticated(response: AuthResponse): Promise<void> {
  currentUser.value = response.user;
  authLoading.value = true;
  try {
    await initializeWorkspace();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Error loading workspace.";
  } finally {
    authLoading.value = false;
  }
}

async function initializeWorkspace(): Promise<void> {
  metadata.value = await getInfo();
  selectedAgent.value = metadata.value.default_agent;
  selectedModel.value = metadata.value.default_model;
  await refreshConversations();
  const requestedThread = getQueryParam("thread_id");
  const conversation = conversations.value.find((item) => item.thread_id === requestedThread);
  if (conversation) {
    await selectConversation(conversation);
  } else {
    newChat();
  }
}

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
        threadId: threadId.value
      });
      appendMessage(response);
    }
    await refreshConversations();
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

async function refreshConversations(): Promise<void> {
  try {
    conversations.value = await listConversations();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Failed to load conversations.";
  }
}

async function selectConversation(conversation: Conversation): Promise<void> {
  if (loading.value) {
    return;
  }
  activeView.value = "chat";
  threadId.value = conversation.thread_id;
  selectedAgent.value = conversation.agent_id;
  selectedModel.value = conversation.model;
  const url = new URL(window.location.href);
  url.searchParams.set("thread_id", threadId.value);
  window.history.replaceState({}, "", url.toString());
  await loadHistory();
}

function newChat(): void {
  activeView.value = "chat";
  messages.value = [];
  renderItems.value = [];
  toolResults.value = {};
  streamingText.value = "";
  selectedFeedback.value = 0;
  feedbackStatus.value = "";
  threadId.value = crypto.randomUUID();
  const url = new URL(window.location.href);
  url.searchParams.set("thread_id", threadId.value);
  window.history.replaceState({}, "", url.toString());
}

async function signOut(): Promise<void> {
  try {
    await logoutUser();
  } catch {
    // Local logout must still succeed if the backend is temporarily unavailable.
  }
  clearAccessToken();
  currentUser.value = null;
  metadata.value = null;
  conversations.value = [];
  messages.value = [];
  renderItems.value = [];
  toolResults.value = {};
  const url = new URL(window.location.href);
  url.searchParams.delete("thread_id");
  url.searchParams.delete("user_id");
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

function getQueryParam(name: string): string {
  const url = new URL(window.location.href);
  return url.searchParams.get(name) ?? "";
}

function formatConversationDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric"
  }).format(new Date(value));
}

function avatarFor(type: ChatMessageType): string {
  if (type === "human") return "👤";
  if (type === "ai") return "🤖";
  if (type === "tool") return "🛠️";
  return "🏭";
}

function avatarClasses(type: ChatMessageType | "task"): string {
  const colors: Record<ChatMessageType | "task", string> = {
    human: "bg-[#ff4b4b]",
    ai: "bg-amber-400",
    tool: "bg-slate-500",
    custom: "bg-slate-600",
    task: "bg-slate-600"
  };
  return `grid size-[34px] place-items-center rounded-lg text-base text-white ${colors[type]}`;
}

function messageContentClasses(type: ChatMessageType): string {
  const contentStyle =
    type === "human"
      ? "bg-slate-50 px-4 py-3 text-slate-800"
      : "bg-transparent py-3 pr-4 text-slate-800";
  return `min-h-12 w-full whitespace-pre-wrap rounded-lg leading-7 ${contentStyle}`;
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
