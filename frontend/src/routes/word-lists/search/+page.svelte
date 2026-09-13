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
	import {
		saveOpenWordPanel, loadOpenWordPanel,
		loadOpenWordPanelNeighbors, loadOpenWordPanelSessionWords,
	} from '$lib/panelWordPersistence';

	// Global list page, same as Known/User/Starred Words - a word found here
	// is viewed with no text/analysis in scope, so WordDetailPanel's UserWord/
	// Visibility sections show every entry read-only except the global one
	// (see isEntryEditable, wordDetailContext.ts).
	const panelContext: WordDetailContext = { type: 'global' };
	// Initialized from panelWordPersistence.ts, same as every other page that
	// opens this modal - recovers which word's panel was open across a
	// mobile browser's involuntary page reload (see its docstring).
	let selectedWordForPanel: string | null = $state(loadOpenWordPanel());
	// Swipe-to-navigate neighbor cache and frozen session order - same
	// mechanism as analyze/[id]/+page.svelte's own (see swipeToWord below
	// and that page's matching declarations for the full picture of why
	// both need to be seeded from sessionStorage rather than starting empty).
	let lastKnownNeighbors: { prev: string | null; next: string | null } = $state(
		(() => {
			const stored = loadOpenWordPanelNeighbors();
			return stored ? { prev: stored.prevWord, next: stored.nextWord } : { prev: null, next: null };
		})()
	);
	let swipeSessionWords: string[] | null = $state(loadOpenWordPanelSessionWords());
	$effect(() => {
		saveOpenWordPanel(
			selectedWordForPanel,
			'default',
			{ prevWord: lastKnownNeighbors.prev, nextWord: lastKnownNeighbors.next },
			swipeSessionWords
		);
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

	// Tracks the open panel word's immediate prev/next in the current
	// `results`, by word identity - same reasoning as analyze/[id]'s own
	// identical effect: only overwritten when the word IS found, so it
	// keeps the last good neighbors instead of clearing to null the moment
	// a fresh search (or a reload) no longer contains it.
	$effect(() => {
		if (!selectedWordForPanel) {
			lastKnownNeighbors = { prev: null, next: null };
			return;
		}
		const idx = results.findIndex((r) => r.word === selectedWordForPanel);
		if (idx === -1) return;
		lastKnownNeighbors = {
			prev: idx > 0 ? results[idx - 1].word : null,
			next: idx < results.length - 1 ? results[idx + 1].word : null,
		};
	});

	// Freezes the swipe order for as long as a panel stays open - captured
	// once, the instant a panel opens from fully closed, and held fixed
	// until it closes, same as analyze/[id]'s own identical effect. Without
	// this, typing a new search query while a panel is open would reshuffle
	// the list out from under an in-progress swipe.
	$effect(() => {
		if (selectedWordForPanel && swipeSessionWords === null) {
			swipeSessionWords = results.map((r) => r.word);
		} else if (!selectedWordForPanel) {
			swipeSessionWords = null;
		}
	});

	// No wraparound at either end - swiping past the last (or before the
	// first) word is a deliberate dead end, same as analyze/[id].
	function swipeToWord(direction: 'next' | 'prev') {
		if (!selectedWordForPanel) return;
		const frozen = swipeSessionWords;
		const idx = frozen ? frozen.indexOf(selectedWordForPanel) : -1;
		let target: string | null;
		if (frozen && idx !== -1) {
			const nextIdx = direction === 'next' ? idx + 1 : idx - 1;
			target = nextIdx >= 0 && nextIdx < frozen.length ? frozen[nextIdx] : null;
		} else {
			const liveIdx = results.findIndex((r) => r.word === selectedWordForPanel);
			if (liveIdx !== -1) {
				const nextIdx = direction === 'next' ? liveIdx + 1 : liveIdx - 1;
				target = nextIdx >= 0 && nextIdx < results.length ? results[nextIdx].word : null;
			} else {
				const candidate = direction === 'next' ? lastKnownNeighbors.next : lastKnownNeighbors.prev;
				target = candidate && results.some((r) => r.word === candidate) ? candidate : null;
			}
		}
		if (!target) return;
		selectedWordForPanel = target;
	}

	// Same click-passthrough pattern as every other row/card in this app -
	// the row itself is a plain div (role="button"), not a <button>, so that
	// a nested interactive element (none today, but kept for consistency)
	// could still handle its own click without also opening the panel.
	function handleRowClick(event: MouseEvent | KeyboardEvent, word: string) {
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
	<p class="text-sm font-medium text-gray-600 dark:text-slate-400 mb-2">Search all sources</p>
	<input
		type="search"
		bind:value={query}
		placeholder="Start typing..."
		class="border border-gray-300 rounded px-3 py-2 text-lg w-full max-w-sm"
	/>
	{#if trimmedQuery && !readyToSearch}
		<p class="text-xs text-amber-600 mt-2">Type at least one Chinese character to search.</p>
	{:else}
		<!-- Wildcard queries anchored anywhere but the very start (e.g. 学*生)
		     stay just as fast as a plain search - Postgres can still use the
		     word index for the literal text before the first '*'. Only a
		     query that OPENS with '*' (e.g. *的) has no literal prefix to
		     index against, so it falls back to a full scan - noticeably
		     slower (see service.search_words' docstring, backend), but still
		     bounded by the same result cap, not a real problem for an
		     occasional, deliberate search like this. -->
		<p class="text-xs text-gray-400 dark:text-slate-500 mt-2">Tip: use * as a wildcard, e.g. 学*生 or *的.</p>
	{/if}
</div>

<!-- Shared flex row with the panel below (lg and up) - same docking
     mechanism as every other word-lists tab. -->
<div class="flex flex-col lg:flex-row gap-4">
	<div class="flex-1 min-w-0 bg-white dark:bg-slate-900 rounded-lg shadow-sm overflow-hidden">
		{#if !trimmedQuery}
			<p class="text-gray-500 dark:text-slate-400 p-4">
				Sources currently include Corpus Frequency, HSK, CC-CEDICT, and your own dictionary entries.
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
						<div
							role="button"
							tabindex="0"
							onclick={(e) => handleRowClick(e, r.word)}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleRowClick(e, r.word); } }}
							class="px-4 py-3 hover:bg-gray-50 dark:hover:bg-slate-800 cursor-pointer"
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
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	<WordDetailModal
		word={selectedWordForPanel}
		context={panelContext}
		onClose={() => selectedWordForPanel = null}
		onSwipeNext={() => swipeToWord('next')}
		onSwipePrevious={() => swipeToWord('prev')}
	/>
</div>
