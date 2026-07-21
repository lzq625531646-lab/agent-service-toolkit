<template>
  <main class="grid min-h-screen place-items-center bg-slate-950 px-5 py-10">
    <div class="grid w-full max-w-[980px] overflow-hidden rounded-3xl bg-white shadow-2xl min-[780px]:grid-cols-[1.05fr_0.95fr]">
      <section class="hidden bg-gradient-to-br from-slate-900 via-slate-800 to-red-950 p-12 text-white min-[780px]:flex min-[780px]:flex-col">
        <div class="text-2xl font-bold">🧰 Agent Service Toolkit</div>
        <div class="my-auto">
          <p class="mb-3 text-sm font-bold uppercase tracking-[0.22em] text-red-300">Private workspace</p>
          <h1 class="mb-5 text-4xl font-bold leading-tight">Your agents and conversations, in one secure place.</h1>
          <p class="max-w-md text-lg leading-8 text-slate-300">
            Sign in to continue previous threads, keep long-term memory tied to your account, and manage your RAG knowledge base.
          </p>
        </div>
        <p class="text-sm text-slate-400">Passwords are protected with Argon2. Sessions can be revoked on logout.</p>
      </section>

      <section class="p-7 min-[780px]:p-12">
        <div class="mb-9 min-[780px]:hidden">
          <div class="text-xl font-bold text-slate-900">🧰 Agent Service Toolkit</div>
        </div>
        <p class="mb-2 text-sm font-bold uppercase tracking-[0.18em] text-red-500">
          {{ mode === "login" ? "Welcome back" : "Create your workspace" }}
        </p>
        <h2 class="mb-2 text-3xl font-bold text-slate-950">
          {{ mode === "login" ? "Sign in" : "Create account" }}
        </h2>
        <p class="mb-8 text-slate-500">
          {{ mode === "login" ? "Continue your saved conversations." : "Start saving private agent conversations." }}
        </p>

        <form class="grid gap-5" @submit.prevent="submit">
          <label v-if="mode === 'register'" class="grid gap-2">
            <span class="text-sm font-semibold text-slate-700">Display name</span>
            <input v-model.trim="displayName" class="auth-input" autocomplete="name" required maxlength="80" />
          </label>
          <label class="grid gap-2">
            <span class="text-sm font-semibold text-slate-700">Email</span>
            <input v-model.trim="email" class="auth-input" type="email" autocomplete="email" required />
          </label>
          <label class="grid gap-2">
            <span class="text-sm font-semibold text-slate-700">Password</span>
            <input
              v-model="password"
              class="auth-input"
              type="password"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              minlength="8"
              maxlength="128"
              required
            />
            <span v-if="mode === 'register'" class="text-xs text-slate-500">At least 8 characters.</span>
          </label>

          <div v-if="error" class="rounded-xl bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">{{ error }}</div>

          <button
            class="mt-1 min-h-12 rounded-xl bg-[#ff4b4b] px-5 font-bold text-white transition hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-60"
            type="submit"
            :disabled="loading"
          >
            {{ loading ? "Please wait…" : mode === "login" ? "Sign in" : "Create account" }}
          </button>
        </form>

        <p class="mt-7 text-center text-sm text-slate-600">
          {{ mode === "login" ? "New here?" : "Already have an account?" }}
          <button class="ml-1 border-0 bg-transparent font-bold text-red-600 hover:underline" type="button" @click="toggleMode">
            {{ mode === "login" ? "Create an account" : "Sign in" }}
          </button>
        </p>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { ref } from "vue";

import { loginUser, registerUser, setAccessToken } from "./api";
import type { AuthResponse } from "./types";

const emit = defineEmits<{ authenticated: [response: AuthResponse] }>();

const mode = ref<"login" | "register">("login");
const displayName = ref("");
const email = ref("");
const password = ref("");
const loading = ref(false);
const error = ref("");

function toggleMode(): void {
  mode.value = mode.value === "login" ? "register" : "login";
  error.value = "";
}

async function submit(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const response =
      mode.value === "login"
        ? await loginUser(email.value, password.value)
        : await registerUser({
            email: email.value,
            displayName: displayName.value,
            password: password.value
          });
    setAccessToken(response.access_token);
    emit("authenticated", response);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Authentication failed.";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.auth-input {
  min-height: 48px;
  width: 100%;
  border: 1px solid rgb(203 213 225);
  border-radius: 0.75rem;
  padding: 0 0.9rem;
  color: rgb(15 23 42);
  outline: none;
  transition: border-color 150ms, box-shadow 150ms;
}

.auth-input:focus {
  border-color: rgb(248 113 113);
  box-shadow: 0 0 0 3px rgb(254 226 226);
}
</style>
