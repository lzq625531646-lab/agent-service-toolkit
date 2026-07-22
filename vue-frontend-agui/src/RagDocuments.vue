<template>
  <main class="min-w-0 bg-slate-50 px-4 py-8 min-[901px]:px-10 min-[901px]:py-12">
    <div class="mx-auto grid max-w-6xl gap-6">
      <header class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p class="mb-2 text-sm font-bold uppercase tracking-[0.16em] text-red-500">Knowledge base</p>
          <h1 class="m-0 text-3xl font-bold text-slate-900">RAG documents</h1>
          <p class="mb-0 mt-2 max-w-2xl leading-7 text-slate-600">
            Upload source documents, monitor indexed chunks, and remove content from PostgreSQL pgvector.
          </p>
        </div>
        <button
          class="min-h-10 rounded-lg border border-slate-300 bg-white px-4 font-semibold text-slate-700 transition hover:bg-slate-100"
          type="button"
          @click="$emit('back')"
        >
          ← Back to chat
        </button>
      </header>

      <section class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div class="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 class="m-0 text-lg font-bold text-slate-900">Add a document</h2>
            <p class="mb-0 mt-1 text-sm text-slate-500">PDF, DOCX, TXT or Markdown · maximum 10 MB</p>
          </div>
          <div class="text-sm font-semibold text-slate-500">Ollama embeddinggemma · 768 dimensions</div>
        </div>

        <form class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]" @submit.prevent="upload">
          <input
            ref="fileInput"
            class="min-h-12 min-w-0 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:font-semibold file:text-white hover:border-slate-400"
            type="file"
            accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
            required
            @change="selectFile"
          />
          <button
            class="min-h-12 rounded-lg bg-[#ff4b4b] px-6 font-bold text-white transition hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-60"
            type="submit"
            :disabled="uploading || !selectedFile"
          >
            {{ uploading ? "Indexing…" : "Upload & index" }}
          </button>
        </form>
      </section>

      <div v-if="message" class="rounded-lg bg-emerald-50 px-4 py-3 font-semibold text-emerald-700">
        {{ message }}
      </div>
      <div v-if="error" class="rounded-lg bg-red-50 px-4 py-3 font-semibold text-red-700">
        {{ error }}
      </div>

      <section class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div class="flex items-center justify-between border-b border-slate-200 px-5 py-4 sm:px-6">
          <div>
            <h2 class="m-0 text-lg font-bold text-slate-900">Indexed documents</h2>
            <p class="mb-0 mt-1 text-sm text-slate-500">
              {{ documents.length }} documents · {{ totalChunks }} chunks
            </p>
          </div>
          <button
            class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            type="button"
            :disabled="loading"
            @click="loadDocuments"
          >
            {{ loading ? "Loading…" : "Refresh" }}
          </button>
        </div>

        <div v-if="!loading && documents.length === 0" class="px-6 py-16 text-center">
          <div class="mb-3 text-4xl">📚</div>
          <p class="m-0 font-semibold text-slate-700">No documents indexed yet</p>
          <p class="mb-0 mt-1 text-sm text-slate-500">Upload a document above to populate the RAG knowledge base.</p>
        </div>

        <div v-else class="overflow-x-auto">
          <table class="w-full border-collapse text-left">
            <thead class="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th class="px-5 py-3 font-bold sm:px-6">Document</th>
                <th class="px-4 py-3 font-bold">Chunks</th>
                <th class="px-4 py-3 font-bold">Size</th>
                <th class="px-4 py-3 font-bold">Indexed</th>
                <th class="px-5 py-3 text-right font-bold sm:px-6">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-for="document in documents" :key="document.id" class="hover:bg-slate-50/70">
                <td class="max-w-md px-5 py-4 sm:px-6">
                  <div class="truncate font-semibold text-slate-900">{{ document.filename }}</div>
                  <div class="mt-1 truncate font-mono text-xs text-slate-400">{{ document.sha256 }}</div>
                </td>
                <td class="px-4 py-4 font-semibold text-slate-700">{{ document.chunk_count }}</td>
                <td class="whitespace-nowrap px-4 py-4 text-slate-600">{{ formatBytes(document.size_bytes) }}</td>
                <td class="whitespace-nowrap px-4 py-4 text-slate-600">{{ formatDate(document.created_at) }}</td>
                <td class="px-5 py-4 text-right sm:px-6">
                  <button
                    class="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-bold text-red-600 transition hover:bg-red-100 disabled:opacity-50"
                    type="button"
                    :disabled="deletingId === document.id"
                    @click="remove(document)"
                  >
                    {{ deletingId === document.id ? "Deleting…" : "Delete" }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { deleteRagDocument, listRagDocuments, uploadRagDocument } from "./api";
import type { RagDocument } from "./types";

defineEmits<{ back: [] }>();

const documents = ref<RagDocument[]>([]);
const selectedFile = ref<File | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const loading = ref(false);
const uploading = ref(false);
const deletingId = ref("");
const error = ref("");
const message = ref("");

const totalChunks = computed(() =>
  documents.value.reduce((total, document) => total + document.chunk_count, 0)
);

onMounted(loadDocuments);

function selectFile(event: Event): void {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null;
  error.value = "";
  message.value = "";
}

async function loadDocuments(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    documents.value = await listRagDocuments();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Failed to load documents.";
  } finally {
    loading.value = false;
  }
}

async function upload(): Promise<void> {
  if (!selectedFile.value || uploading.value) return;
  uploading.value = true;
  error.value = "";
  message.value = "";
  try {
    const document = await uploadRagDocument(selectedFile.value);
    documents.value = [document, ...documents.value];
    message.value = `${document.filename} indexed successfully with ${document.chunk_count} chunks.`;
    selectedFile.value = null;
    if (fileInput.value) fileInput.value.value = "";
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Document upload failed.";
  } finally {
    uploading.value = false;
  }
}

async function remove(document: RagDocument): Promise<void> {
  if (!window.confirm(`Delete ${document.filename} and all of its indexed chunks?`)) return;
  deletingId.value = document.id;
  error.value = "";
  message.value = "";
  try {
    await deleteRagDocument(document.id);
    documents.value = documents.value.filter((item) => item.id !== document.id);
    message.value = `${document.filename} was deleted.`;
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Document deletion failed.";
  } finally {
    deletingId.value = "";
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value)
  );
}
</script>
