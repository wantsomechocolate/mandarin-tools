<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import {
		familiarityColor, familiarityLabel,
		rarityColor, rarityLabel,
		sourceDetailLabel, sourceDetailColor,
		type SourceDetailTier,
	} from '$lib/wordDisplay';
	import WordDetailModal from '$lib/components/WordDetailModal.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';
	import { saveOpenWordPanel, loadOpenWordPanel } from '$lib/panelWordPersistence';

	// Global list page, same as Known/User/Starred Words - a word found here
	// is viewed with no text/analysis in scope, so WordDetailPanel's UserWord/
	// Visibility sections show every entry read-only except the global one
	// (see isEntryEditable, wordDetailContext.ts).
	const panelContext: WordDetailContext = { type: 'global' };
	let selectedWordForPanel: string | null = $state(loadOpenWordPanel());
	$effect(() => {
		saveOpenWordPanel(selectedWordForPanel);
	});

	// Same CJK range as the results page's own containsChinese
	// (analyze/[id]/+page.svelte) and the backend's mirror of it
	// (service._CJK_RE) - kept as its own copy per this codebase's
	// per-file-snippet convention, same as every other duplicate of this
	// exact check.
	function containsChinese(text: string): boolean {
		return /[一-鿿]/.test(text);
	}

	interface WordSearchResult {
		word: string;
		pinyin: string | null;
		preview_meaning: string | null;
		hsk_v2_2012: number | null;
		hsk_v3_2021: number | null;
		hsk_v3_2026: number | null;
		freq_per_million: number | null;
		rarity_tier: string | null;
		sources: SourceDetailTier[];
		is_user_word: boolean;
		familiarity: number | null;
		is_starred: boolean;
		is_garbage: boolean;
	}

	let query = $state('');
	let results: WordSearchResult[] = $state([]);
	let truncated = $state(false);
	let loading = $state(false);
	let error = $state('');
	let searchedAtLeastOnce = $state(false);

	const trimmedQuery = $derived(query.trim());
	const readyToSearch = $derived(trimmedQuery.length > 0 && containsChinese(trimmedQuery));

	// Debounced, not on every keystroke - a search-as-you-type box firing a
	// request per character would mostly just cancel itself out on a normal
	// typing cadence. 200ms, not persisted across reloads - unlike Known
	// Words' search box (a standing filter over an already-loaded list),
	// this one drives a network request each time, so there's no benefit to
	// restoring a stale query on return.
	let debounceTimeout: ReturnType<typeof setTimeout> | undefined;
	let requestId = 0;

	$effect(() => {
		const q = trimmedQuery;
		clearTimeout(debounceTimeout);
		if (!readyToSearch) {
			loading = false;
			results = [];
			truncated = false;
			return;
		}
		debounceTimeout = setTimeout(() => runSearch(q), 200);
		return () => clearTimeout(debounceTimeout);
	});

	async function runSearch(q: string) {
		const thisRequest = ++requestId;
		loading = true;
		error = '';
		try {
			const response = await api.searchWords(q) as { results: WordSearchResult[]; truncated: boolean };
			// A slower earlier request resolving after a faster later one
			// would otherwise clobber the current, more-relevant results with
			// stale ones - only the most recently *issued* request is allowed
			// to write.
			if (thisRequest !== requestId) return;
			results = response.results;
			truncated = response.truncated;
			searchedAtLeastOnce = true;
		} catch (e: unknown) {
			if (thisRequest !== requestId) return;
			error = e instanceof Error ? e.message : 'Search failed';
		} finally {
			if (thisRequest === requestId) loading = false;
		}
	}

	onMount(() => {
		if (!isLoggedIn()) {
			goto('/login');
		}
	});

	function handleRowClick(event: MouseEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		selectedWordForPanel = word;
	}
</script>

<svelte:head><title>Word Search - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 dark:text-slate-400 mb-2">Search every source at once</p>
	<input
		type="search"
		bind:value={query}
		placeholder="Type a Chinese word..."
		class="border border-gray-300 rounded px-3 py-2 text-lg w-full max-w-sm"
	/>
	{#if trimmedQuery && !readyToSearch}
		<p class="text-xs text-amber-600 mt-2">Type at least one Chinese character to search.</p>
	{/if}
</div>

<!-- Shared flex row with the panel below (lg and up) - same docking
     mechanism as every other word-lists tab. -->
<div class="flex flex-col lg:flex-row gap-4">
	<div class="flex-1 min-w-0 bg-white dark:bg-slate-900 rounded-lg shadow-sm overflow-hidden">
		{#if !trimmedQuery}
			<p class="text-gray-500 dark:text-slate-400 p-4">
				Start typing to search HSK, CC-CEDICT, corpus frequency, and your own dictionary entries at once.
			</p>
		{:else if !readyToSearch}
			<!-- The amber hint above already explains why - nothing more to say here. -->
		{:else if loading && results.length === 0}
			<p class="text-gray-500 dark:text-slate-400 p-4">Searching...</p>
		{:else if searchedAtLeastOnce && results.length === 0}
			<p class="text-gray-500 dark:text-slate-400 p-4">No matches for "{trimmedQuery}".</p>
		{:else}
			{#if truncated}
				<p class="text-xs text-amber-600 dark:text-amber-400 px-4 pt-3">
					Showing the top {results.length} matches - keep typing to narrow this down.
				</p>
			{/if}
			<ul class="divide-y divide-gray-100 dark:divide-slate-800">
				{#each results as r (r.word)}
					<li>
						<button
							type="button"
							class="w-full text-left px-4 py-3 hover:bg-gray-50 dark:hover:bg-slate-800 cursor-pointer"
							onclick={(e) => handleRowClick(e, r.word)}
						>
							<div class="flex items-baseline gap-2 flex-wrap">
								<span class="text-lg font-medium">{r.word}</span>
								{#if r.pinyin}<span class="text-sm text-gray-500 dark:text-slate-400">{r.pinyin}</span>{/if}
								{#if r.is_starred}<span class="text-amber-500" title="Starred">★</span>{/if}
								{#if r.is_garbage}<span class="text-xs text-gray-400 dark:text-slate-500" title="Marked as garbage">(garbage)</span>{/if}
							</div>
							{#if r.preview_meaning}
								<p class="text-sm text-gray-600 dark:text-slate-400 mt-0.5 truncate">{r.preview_meaning}</p>
							{/if}
							<div class="flex items-center gap-1.5 flex-wrap mt-1.5">
								{#each r.sources as source}
									<span class="text-xs px-2 py-0.5 rounded-full {sourceDetailColor(source)}">{sourceDetailLabel(source)}</span>
								{/each}
								{#if r.hsk_v2_2012}
									<span class="text-xs px-2 py-0.5 bg-blue-100 dark:bg-blue-500/15 text-blue-700 dark:text-blue-400 rounded-full">HSK 2012: {r.hsk_v2_2012}</span>
								{/if}
								{#if r.hsk_v3_2021}
									<span class="text-xs px-2 py-0.5 bg-purple-100 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300 rounded-full">HSK 2021: {r.hsk_v3_2021}</span>
								{/if}
								{#if r.hsk_v3_2026}
									<span class="text-xs px-2 py-0.5 bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300 rounded-full">HSK 2026: {r.hsk_v3_2026}</span>
								{/if}
								{#if r.rarity_tier}
									<span class="text-xs px-2 py-0.5 rounded-full {rarityColor(r.rarity_tier)}" title={r.freq_per_million ? `${r.freq_per_million.toFixed(2)} per million` : undefined}>{rarityLabel(r.rarity_tier)}</span>
								{/if}
								{#if r.familiarity !== null}
									<span class="text-xs px-2 py-0.5 rounded-full {familiarityColor(r.familiarity)}">{familiarityLabel(r.familiarity)}</span>
								{/if}
							</div>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	<WordDetailModal
		word={selectedWordForPanel}
		context={panelContext}
		onClose={() => selectedWordForPanel = null}
	/>
</div>
