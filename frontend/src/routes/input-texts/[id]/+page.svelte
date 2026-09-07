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

{#snippet iconHome()}
	<svg class="w-8 h-8" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 9.5L10 4l6.5 5.5" />
		<path d="M5 8.5v7a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-7" />
		<path d="M8 16.5v-4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v4" />
	</svg>
{/snippet}

<!-- Bar-chart glyph for "results" links - the header's "See latest results"
     next to the title, and each row's own "View results" in the Analyses
     list below. Same glyph, two sizes (the header one sits at 8x8 like the
     home icon beside it; each list row is smaller at 7x7), so this takes
     its size as a parameter rather than being duplicated. The counterpart
     to analyze/[id]'s own book icon (View source text): book = the text,
     chart = what came out of analyzing it, rather than an app-specific
     "segmented text" glyph nobody's seen before. -->
{#snippet iconBarChart(sizeClass: string)}
	<svg class={sizeClass} viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 16.5h13" />
		<path d="M6 16.5V11" />
		<path d="M10 16.5V6.5" />
		<path d="M14 16.5V9" />
	</svg>
{/snippet}

<div class="min-h-screen bg-gray-50">
	<!-- Same dynamic-title risk as analyze/[id] (a Chinese title has no
	     spaces to wrap on) even though this row has no competing right-side
	     content today - min-w-0 + truncate + title= protects it now and
	     keeps it safe if a right-side cluster is ever added here later.
	     justify-between dropped: this row has only one flex child. -->
	<nav class="bg-white shadow-sm px-6 py-4 flex items-center">
		<div class="flex items-center gap-4 min-w-0">
			<a href="/" class="text-gray-400 hover:text-blue-600 shrink-0" aria-label="Home" title="Home">
				{@render iconHome()}
			</a>
			<h1 class="text-xl font-bold text-gray-800 min-w-0 truncate" title={inputText?.title ?? 'Untitled'}>
				{inputText?.title ?? 'Untitled'}
			</h1>
			{#if inputText && inputText.analyses.length > 0}
				<a
					href="/analyze/{inputText.analyses[0].id}"
					class="text-gray-400 hover:text-blue-600 shrink-0"
					aria-label="View latest results"
					title="View latest results"
				>
					{@render iconBarChart('w-8 h-8')}
				</a>
			{/if}
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
								<span class="text-gray-400" title="View results">
									{@render iconBarChart('w-7 h-7')}
									<span class="sr-only">View results</span>
								</span>
							</a>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</main>
</div>
