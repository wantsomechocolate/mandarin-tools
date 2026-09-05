<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	interface AnalysisSummary {
		id: number;
		created_at: string;
		total_words: number;
		unique_words: number;
		min_token_length: number;
		max_token_length: number;
		min_token_count: number;
		min_familiarity_filter: number;
		max_familiarity_filter: number;
	}

	interface InputTextDetail {
		id: number;
		title: string | null;
		body: string;
		created_at: string;
		updated_at: string;
		analyses: AnalysisSummary[];
	}

	let inputText: InputTextDetail | null = $state(null);
	let loading = $state(true);
	let error = $state('');
	let reanalyzing = $state(false);

	const id = $derived(parseInt($page.params.id ?? '0'));

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			inputText = await api.getInputText(id) as InputTextDetail;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load text';
		} finally {
			loading = false;
		}
	});

	async function handleReanalyze() {
		reanalyzing = true;
		error = '';
		try {
			const result = await api.reanalyzeInputText(id) as any;
			goto(`/analyze/${result.analysis_id}`);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to re-analyze';
			reanalyzing = false;
		}
	}
</script>

<div class="min-h-screen bg-gray-50">
	<!-- Same dynamic-title risk as analyze/[id] (a Chinese title has no
	     spaces to wrap on) even though this row has no competing right-side
	     content today - min-w-0 + truncate + title= protects it now and
	     keeps it safe if a right-side cluster is ever added here later.
	     justify-between dropped: this row has only one flex child. -->
	<nav class="bg-white shadow-sm px-6 py-4 flex items-center">
		<div class="flex items-center gap-4 min-w-0">
			<a href="/" class="text-gray-600 hover:text-gray-800 text-sm shrink-0">← Back</a>
			<h1 class="text-xl font-bold text-gray-800 min-w-0 truncate" title={inputText?.title ?? 'Untitled'}>
				{inputText?.title ?? 'Untitled'}
			</h1>
		</div>
	</nav>

	<main class="max-w-3xl mx-auto px-6 py-8">
		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		{#if loading}
			<p class="text-gray-500">Loading...</p>
		{:else if inputText}
			<!-- Source text -->
			<div class="bg-white rounded-lg shadow-sm p-6 mb-6">
				<div class="flex justify-between items-start mb-4">
					<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Source text</p>
					<p class="text-xs text-gray-400">
						Added {new Date(inputText.created_at).toLocaleDateString()}
					</p>
				</div>
				<p class="whitespace-pre-wrap leading-relaxed text-gray-800">{inputText.body}</p>
			</div>

			<!-- Analyses -->
			<div class="bg-white rounded-lg shadow-sm p-6">
				<div class="flex justify-between items-center mb-4">
					<h2 class="text-lg font-semibold text-gray-800">
						Analyses ({inputText.analyses.length})
					</h2>
					<button
						onclick={handleReanalyze}
						disabled={reanalyzing}
						class="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
					>
						{reanalyzing ? 'Analyzing...' : '+ Re-analyze'}
					</button>
				</div>

				{#if inputText.analyses.length === 0}
					<p class="text-gray-400 text-sm">No analyses yet.</p>
				{:else}
					<div class="space-y-2">
						{#each inputText.analyses as analysis}
							<a
								href="/analyze/{analysis.id}"
								class="flex justify-between items-center border border-gray-100 rounded-md px-4 py-3 hover:bg-gray-50"
							>
								<div>
									<p class="text-sm font-medium text-gray-800">
										{new Date(analysis.created_at).toLocaleString()}
									</p>
									<p class="text-xs text-gray-500 mt-0.5">
										{analysis.unique_words} unique words · {analysis.total_words} total occurrences
									</p>
								</div>
								<span class="text-blue-600 text-sm">View results →</span>
							</a>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</main>
</div>
