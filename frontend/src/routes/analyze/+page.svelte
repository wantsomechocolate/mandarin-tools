<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';

	let title = $state('');
	let body = $state('');
	let error = $state('');
	let loading = $state(false);

	onMount(() => {
		if (!isLoggedIn()) goto('/login');
	});

	async function handleSubmit() {
		if (!body.trim()) {
			error = 'Please enter some text to analyze';
			return;
		}
		error = '';
		loading = true;
		try {
			const result = await api.analyzeText(title || null, body) as any;
			goto(`/analyze/${result.analysis_id}`);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Analysis failed';
		} finally {
			loading = false;
		}
	}
</script>

<div class="min-h-screen bg-gray-50">
	<!-- No mobile-stacking fix needed: "New Analysis" is a fixed, short
	     English string (no dynamic title, no per-text length risk) and
	     there's no competing right-side cluster - the one-character-per-
	     line failure mode this pass fixes elsewhere can't occur here. -->
	<nav class="bg-white shadow-sm px-6 py-4 flex justify-between items-center">
		<div class="flex items-center gap-4">
			<a href="/" class="text-gray-600 hover:text-gray-800 text-sm">← Back</a>
			<h1 class="text-xl font-bold text-gray-800">New Analysis</h1>
		</div>
	</nav>

	<main class="max-w-3xl mx-auto px-6 py-8">
		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		<div class="bg-white rounded-lg shadow-sm p-6 space-y-4">
			<div>
				<label class="block text-sm font-medium text-gray-700 mb-1" for="title">
					Title <span class="text-gray-400 font-normal">(optional)</span>
				</label>
				<input
					id="title"
					type="text"
					bind:value={title}
					class="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
					placeholder="e.g. Chapter 1 of my textbook"
				/>
			</div>

			<div>
				<label class="block text-sm font-medium text-gray-700 mb-1" for="body">
					Chinese text
				</label>
				<textarea
					id="body"
					bind:value={body}
					rows="12"
					class="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 font-sans"
					placeholder="Paste your Chinese text here..."
				></textarea>
			</div>

			<button
				onclick={handleSubmit}
				disabled={loading}
				class="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
			>
				{loading ? 'Analyzing...' : 'Analyze'}
			</button>
		</div>
	</main>
</div>