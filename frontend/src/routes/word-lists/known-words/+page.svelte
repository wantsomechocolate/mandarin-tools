<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import { familiarityLabel } from '$lib/wordDisplay';
	import WordDetailModal from '$lib/components/WordDetailModal.svelte';
	import FamiliarityDots from '$lib/components/FamiliarityDots.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';
	import { saveOpenWordPanel, loadOpenWordPanel } from '$lib/panelWordPersistence';

	// Filter preferences persist across reloads as a global per-browser
	// setting - same localStorage pattern analyze/[id] already established
	// (FILTER_STORAGE_KEY there), but unlike that page, search is included
	// here: analyze/[id] deliberately excludes it because a stale search
	// term left over from a *different analysis's* words would be
	// confusing, but this page is the same running list across every
	// visit, so persisting the search box too is the more helpful default,
	// not a stale-content risk. Every other profile list page (User Words,
	// Garbage Words, Starred Words, Stopwords) follows this same shape,
	// each with its own storage key and its own subset of fields.
	const FILTER_STORAGE_KEY = 'mandarin_tools_known_words_filters';

	interface StoredFilters {
		search: string;
		familiarityMode: FamiliarityFilterMode;
		familiarityValue: number;
		sortColumn: SortColumn;
		sortDirection: 'asc' | 'desc';
	}

	function loadStoredFilters(): Partial<StoredFilters> {
		if (!browser) return {};
		try {
			const raw = localStorage.getItem(FILTER_STORAGE_KEY);
			return raw ? JSON.parse(raw) : {};
		} catch {
			return {};
		}
	}

	const storedFilters = loadStoredFilters();

	// Global list page - every word here is viewed with no text/analysis in
	// scope, so WordDetailPanel.svelte's UserWord/Visibility sections show
	// every entry read-only except the global one (see isEntryEditable,
	// wordDetailContext.ts - this falls out of the hierarchy rule with no
	// special case for "global page").
	const panelContext: WordDetailContext = { type: 'global' };
	// See panelWordPersistence.ts's docstring - recovers which word's panel
	// was open across a mobile browser's involuntary page reload.
	let selectedWordForPanel: string | null = $state(loadOpenWordPanel());
	$effect(() => {
		saveOpenWordPanel(selectedWordForPanel);
	});

	interface KnownWord {
		id: number;
		word: string;
		familiarity: number | null;
	}

	let words: KnownWord[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state(storedFilters.search ?? '');
	let updatingWord: string | null = $state(null);

	let newWord = $state('');
	let newFamiliarity: number = $state(5);
	let adding = $state(false);

	// 'lte' is the primary use case (narrow down to less-familiar words);
	// 'eq' is a secondary, exact-match option - both share one value
	// selector rather than two independent controls, since only one mode
	// is ever active at a time.
	type FamiliarityFilterMode = 'all' | 'lte' | 'eq';
	let familiarityMode: FamiliarityFilterMode = $state(storedFilters.familiarityMode ?? 'all');
	let familiarityValue = $state(storedFilters.familiarityValue ?? 5);

	type SortColumn = 'word' | 'familiarity' | null;
	let sortColumn: SortColumn = $state(storedFilters.sortColumn ?? null);
	let sortDirection: 'asc' | 'desc' = $state(storedFilters.sortDirection ?? 'asc');

	function toggleSort(column: Exclude<SortColumn, null>) {
		if (sortColumn !== column) {
			sortColumn = column;
			sortDirection = 'asc';
		} else if (sortDirection === 'asc') {
			sortDirection = 'desc';
		} else {
			sortColumn = null;
		}
	}

	// Persist filter preferences on every change - see FILTER_STORAGE_KEY's
	// comment above for what's included here and why.
	$effect(() => {
		if (!browser) return;
		try {
			const toStore: StoredFilters = { search, familiarityMode, familiarityValue, sortColumn, sortDirection };
			localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(toStore));
		} catch {
			// e.g. storage disabled/full - filters just won't persist, no need to surface an error
		}
	});

	onMount(() => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		// Fired independently (not Promise.all), same reasoning as
		// word-lists/+page.svelte's own count-loading - the HSK counts are a
		// secondary, "bulk tools" concern, and shouldn't hold back the main
		// list (or vice versa) if one is slow or fails.
		api.listKnownWords()
			.then((r: unknown) => words = r as KnownWord[])
			.catch((e: unknown) => error = e instanceof Error ? e.message : 'Failed to load known words')
			.finally(() => loading = false);

		api.getHskLevelCounts()
			.then((r: unknown) => {
				const counts = r as HskLevelCounts;
				hskCounts = counts;
				// Pre-fills the bulk-assign section's own per-row familiarity
				// pickers with a sensible descending default (lower HSK level =
				// more basic = "should already be mastered if you're using this
				// app seriously") - fully editable per row before clicking
				// Apply, this is just a starting point, not a forced value.
				const initial: Record<string, number> = {};
				for (const { level } of counts.v2012) initial[bulkKey('2012', level)] = defaultFamiliarityForLevel(level);
				for (const { level } of counts.v2026) initial[bulkKey('2026', level)] = defaultFamiliarityForLevel(level);
				bulkFamiliarityByKey = initial;
			})
			.catch((e: unknown) => hskCountsError = e instanceof Error ? e.message : 'Failed to load HSK level counts');
	});

	// Bulk-assign by HSK level - lets a new user (or one adding a new HSK
	// edition's data) skip hand-scoring hundreds/thousands of words one at a
	// time. HSK 2021 is deliberately not offered (see bulk_assign_hsk_familiarity's
	// docstring, router.py) - a product decision, not an oversight.
	interface HskLevelCount { level: number; word_count: number; }
	interface HskLevelCounts { v2012: HskLevelCount[]; v2026: HskLevelCount[]; }

	let bulkExpanded = $state(false);
	let hskCounts: HskLevelCounts | null = $state(null);
	let hskCountsError = $state('');
	let bulkOverwrite = $state(false);
	// Keyed by bulkKey(edition, level) - one entry per one of the 13 rows.
	let bulkFamiliarityByKey: Record<string, number> = $state({});
	let bulkApplying: string | null = $state(null);
	let bulkResultByKey: Record<string, { matched: number; updated: number; skipped: number }> = $state({});
	let bulkErrorByKey: Record<string, string> = $state({});

	function bulkKey(edition: '2012' | '2026', level: number): string {
		return `${edition}-${level}`;
	}

	// level 1 -> 5 (Mastered), 2 -> 4, 3 -> 3, 4 -> 2, 5/6/7 -> 1 (Seen it) -
	// see this function's own callers for why this is only ever a starting
	// point, never forced.
	function defaultFamiliarityForLevel(level: number): number {
		return Math.max(1, 6 - level);
	}

	async function applyBulkAssign(edition: '2012' | '2026', level: number) {
		const key = bulkKey(edition, level);
		const familiarity = bulkFamiliarityByKey[key] ?? defaultFamiliarityForLevel(level);
		const levelCounts = edition === '2012' ? hskCounts?.v2012 : hskCounts?.v2026;
		const matched = levelCounts?.find((l) => l.level === level)?.word_count ?? 0;

		// Only the destructive path (replacing scores you already set) is
		// gated - the additive default (overwrite off) can't lose any data,
		// so it just runs. The count shown here is exact, not an estimate -
		// with overwrite on, every matched word gets this call's familiarity
		// regardless of whether it already had a different one, so "matched"
		// and "affected" are the same number.
		if (bulkOverwrite) {
			const proceed = confirm(
				`Set familiarity to "${familiarityLabel(familiarity)}" for all ${matched.toLocaleString()} HSK ${edition} level ${level} words, replacing any scores they already have?`
			);
			if (!proceed) return;
		}

		bulkApplying = key;
		try {
			const result = await api.bulkAssignHskFamiliarity(edition, level, familiarity, bulkOverwrite) as { matched: number; updated: number; skipped: number };
			bulkResultByKey = { ...bulkResultByKey, [key]: result };
			if (key in bulkErrorByKey) {
				const { [key]: _dropped, ...rest } = bulkErrorByKey;
				bulkErrorByKey = rest;
			}
			// A bulk action can add/update thousands of rows at once - the
			// endpoint only returns counts, not which words, so the simplest
			// correct way to reflect that here is a full refetch rather than
			// trying to patch `words` incrementally.
			words = await api.listKnownWords() as KnownWord[];
		} catch (e: unknown) {
			bulkErrorByKey = { ...bulkErrorByKey, [key]: e instanceof Error ? e.message : 'Failed to apply' };
		} finally {
			bulkApplying = null;
		}
	}

	const filtered = $derived(() => {
		const q = search.trim();
		let list = q ? words.filter((w) => w.word.includes(q)) : words;
		if (familiarityMode === 'lte') {
			list = list.filter((w) => w.familiarity !== null && w.familiarity <= familiarityValue);
		} else if (familiarityMode === 'eq') {
			list = list.filter((w) => w.familiarity === familiarityValue);
		}
		if (sortColumn) {
			list = [...list].sort((a, b) => {
				// Plain codepoint comparison for word - not localeCompare with a
				// 'zh' locale, which sorts by pinyin (see the results page's
				// identical reasoning, CLAUDE.md).
				let cmp = sortColumn === 'word'
					? (a.word < b.word ? -1 : a.word > b.word ? 1 : 0)
					: (a.familiarity ?? -1) - (b.familiarity ?? -1);
				return sortDirection === 'desc' ? -cmp : cmp;
			});
		}
		return list;
	});

	// Clearing familiarity (familiarity === null) now deletes the row
	// server-side rather than leaving an orphaned null-familiarity one (see
	// upsert_known_word's docstring, router.py) - a KnownWord row's entire
	// reason to exist is to hold a score, so a cleared word is no longer
	// "known" and drops out of this list entirely, not just its score
	// column. (The response is null in that case, so this reads
	// `familiarity` - the value just sent - rather than the response.)
	async function setFamiliarity(word: string, familiarity: number | null) {
		updatingWord = word;
		try {
			await api.upsertKnownWord(word, familiarity);
			if (familiarity === null) {
				words = words.filter((w) => w.word !== word);
			} else {
				words = words.map((w) => w.word === word ? { ...w, familiarity } : w);
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update familiarity';
		} finally {
			updatingWord = null;
		}
	}

	// Same click-passthrough pattern as the analysis results page
	// (handleRowClick, analyze/[id]/+page.svelte) - clicking anywhere on
	// the row opens the panel, unless the click landed on an actual
	// interactive element within it, which handles itself.
	function handleRowClick(event: MouseEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		selectedWordForPanel = word;
	}

	// Reactive so the form can warn before submission - see the template's
	// warning message and button label, both keyed off this.
	const existingKnownWord = $derived(words.find((w) => w.word === newWord.trim()) ?? null);

	// Used to silently no-op when the word was already known - upsertKnownWord
	// is itself an upsert (see its docstring, router.py), so the guard was
	// only ever blocking the *frontend* from calling an endpoint that would
	// have worked fine; it just never told the user why nothing happened.
	// Unlike User Words below, there's no other field on this row (just the
	// one familiarity score, which the form already collects a fresh value
	// for), so letting this proceed as a real update - with the warning
	// making the update explicit rather than a surprise - is safe, and is
	// actually the more useful behavior: re-adding a known word with a
	// different score in the picker now really does re-score it, matching
	// what a user would reasonably expect instead of nothing happening.
	async function addWord() {
		const word = newWord.trim();
		if (!word) return;
		adding = true;
		try {
			const created = await api.upsertKnownWord(word, newFamiliarity) as KnownWord;
			const alreadyListed = words.some((w) => w.word === word);
			words = alreadyListed ? words.map((w) => w.word === word ? created : w) : [created, ...words];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add word';
		} finally {
			adding = false;
		}
	}
</script>

<!-- Same up/down chevron as the results page's own sortHeader (analyze/[id])
     - rotated = ascending, unrotated = descending - rather than the plain
     "(asc)"/"(desc)" text this page used before. Kept as its own copy per
     this codebase's per-file icon-snippet convention. -->
{#snippet iconChevron(expanded: boolean)}
	<svg
		class="w-4 h-4 transition-transform {expanded ? 'rotate-180' : ''}"
		viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
	>
		<path d="M5 7.5l5 5 5-5" />
	</svg>
{/snippet}

<svelte:head><title>Known Words - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- Known words are always global (see KnownWord's docstring, models.py) -
     no scope column needed here, unlike User Words. -->
<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 dark:text-slate-400 mb-2">Add a word</p>
	<div class="flex flex-wrap items-center gap-2">
		<input
			type="text"
			bind:value={newWord}
			placeholder="Chinese word..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
			onkeydown={(e) => { if (e.key === 'Enter') addWord(); }}
		/>
		<select bind:value={newFamiliarity} class="border border-gray-300 rounded px-2 py-1 text-sm">
			{#each [1, 2, 3, 4, 5] as score}
				<option value={score}>{score} - {familiarityLabel(score)}</option>
			{/each}
		</select>
		<button
			onclick={addWord}
			disabled={!newWord.trim() || adding}
			class="text-sm px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
		>
			{adding ? 'Adding...' : existingKnownWord ? 'Update familiarity' : 'Add'}
		</button>
	</div>
	{#if existingKnownWord}
		<p class="text-xs text-amber-600 mt-2">
			"{existingKnownWord.word}" is already known ({existingKnownWord.familiarity !== null ? `familiarity: ${familiarityLabel(existingKnownWord.familiarity)}` : 'no score set'}) — adding here will update it to {newFamiliarity} - {familiarityLabel(newFamiliarity)}.
		</p>
	{/if}
</div>

<!-- Collapsed by default - a power tool for getting a baseline in place
     fast (the app "takes a long time to start being useful" otherwise -
     scoring HSK1-6/HSK1-7 word-by-word), not something a returning user
     needs to see every visit. -->
<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4 mb-4">
	<button
		onclick={() => bulkExpanded = !bulkExpanded}
		class="w-full flex items-center justify-between text-sm font-medium text-gray-600 dark:text-slate-400 hover:text-gray-800 dark:hover:text-slate-200"
	>
		<span>Bulk-assign by HSK level</span>
		{@render iconChevron(bulkExpanded)}
	</button>
	{#if bulkExpanded}
		<div class="mt-3 space-y-4">
			<p class="text-xs text-gray-500 dark:text-slate-400">
				Sets familiarity for every dictionary word at a given HSK level in one go. HSK 2021 isn't
				offered here - HSK 2012 and the newer 2026 standard cover this instead.
			</p>
			<label class="flex items-center gap-1.5 text-sm text-gray-600 dark:text-slate-400">
				<input type="checkbox" bind:checked={bulkOverwrite} class="rounded border-gray-300" />
				Overwrite words that already have a familiarity score
			</label>

			{#if hskCountsError}
				<p class="text-xs text-red-600 dark:text-red-400">{hskCountsError}</p>
			{:else if !hskCounts}
				<p class="text-xs text-gray-400 dark:text-slate-500">Loading HSK level counts...</p>
			{:else}
				<div>
					<p class="text-xs font-semibold text-gray-500 dark:text-slate-400 mb-1.5">HSK 2012</p>
					<div class="space-y-1.5">
						{#each hskCounts.v2012 as { level, word_count } (level)}
							{@const key = bulkKey('2012', level)}
							<div class="flex flex-wrap items-center gap-2 text-sm">
								<span class="w-16 text-gray-700 dark:text-slate-300">Level {level}</span>
								<span class="w-24 text-xs text-gray-400 dark:text-slate-500">{word_count.toLocaleString()} words</span>
								<select bind:value={bulkFamiliarityByKey[key]} class="border border-gray-300 rounded px-2 py-1 text-sm">
									{#each [1, 2, 3, 4, 5] as score}
										<option value={score}>{score} - {familiarityLabel(score)}</option>
									{/each}
								</select>
								<button
									onclick={() => applyBulkAssign('2012', level)}
									disabled={bulkApplying === key}
									class="text-sm px-3 py-1 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
								>
									{bulkApplying === key ? 'Applying...' : 'Apply'}
								</button>
								{#if bulkResultByKey[key]}
									<span class="text-xs text-emerald-600">
										Set {bulkResultByKey[key].updated.toLocaleString()} word{bulkResultByKey[key].updated === 1 ? '' : 's'}{#if bulkResultByKey[key].skipped > 0} ({bulkResultByKey[key].skipped.toLocaleString()} already scored, skipped){/if}
									</span>
								{/if}
								{#if bulkErrorByKey[key]}
									<span class="text-xs text-red-600 dark:text-red-400">{bulkErrorByKey[key]}</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>

				<div>
					<p class="text-xs font-semibold text-gray-500 dark:text-slate-400 mb-1.5">HSK 2026</p>
					<div class="space-y-1.5">
						{#each hskCounts.v2026 as { level, word_count } (level)}
							{@const key = bulkKey('2026', level)}
							<div class="flex flex-wrap items-center gap-2 text-sm">
								<span class="w-16 text-gray-700 dark:text-slate-300">Level {level}</span>
								<span class="w-24 text-xs text-gray-400 dark:text-slate-500">{word_count.toLocaleString()} words</span>
								<select bind:value={bulkFamiliarityByKey[key]} class="border border-gray-300 rounded px-2 py-1 text-sm">
									{#each [1, 2, 3, 4, 5] as score}
										<option value={score}>{score} - {familiarityLabel(score)}</option>
									{/each}
								</select>
								<button
									onclick={() => applyBulkAssign('2026', level)}
									disabled={bulkApplying === key}
									class="text-sm px-3 py-1 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
								>
									{bulkApplying === key ? 'Applying...' : 'Apply'}
								</button>
								{#if bulkResultByKey[key]}
									<span class="text-xs text-emerald-600">
										Set {bulkResultByKey[key].updated.toLocaleString()} word{bulkResultByKey[key].updated === 1 ? '' : 's'}{#if bulkResultByKey[key].skipped > 0} ({bulkResultByKey[key].skipped.toLocaleString()} already scored, skipped){/if}
									</span>
								{/if}
								{#if bulkErrorByKey[key]}
									<span class="text-xs text-red-600 dark:text-red-400">{bulkErrorByKey[key]}</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>

<div class="flex items-center justify-between mb-3 gap-3 flex-wrap">
	<div class="flex items-center gap-2 flex-wrap">
		<input
			type="search"
			bind:value={search}
			placeholder="Search words..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-48"
		/>
		<span class="flex items-center gap-1.5 text-sm text-gray-700 dark:text-slate-300">
			Familiarity
			<select bind:value={familiarityMode} class="border border-gray-300 rounded px-2 py-1 text-sm">
				<option value="all">All</option>
				<option value="lte">≤</option>
				<option value="eq">=</option>
			</select>
			{#if familiarityMode !== 'all'}
				<select bind:value={familiarityValue} class="border border-gray-300 rounded px-2 py-1 text-sm">
					{#each [1, 2, 3, 4, 5] as score}
						<option value={score}>{score}</option>
					{/each}
				</select>
			{/if}
		</span>
	</div>
	<span class="text-sm text-gray-400 dark:text-slate-500">{filtered().length} of {words.length} words</span>
</div>

<!-- Shared flex row with the panel below (lg and up) - same mechanism as
     the analysis results page: the panel's own backdrop wrapper collapses
     to `display: contents` at `lg`, so its child joins this row as a
     sticky-positioned sibling instead of floating as a modal. -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white dark:bg-slate-900 rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 dark:text-slate-400 p-4">Loading...</p>
	{:else if words.length === 0}
		<p class="text-gray-500 dark:text-slate-400 p-4">No known words yet - add one above, or mark familiarity from any analysis.</p>
	{:else}
		<table class="w-full">
			<thead class="bg-gray-50 dark:bg-slate-950 border-b border-gray-200 dark:border-slate-800">
				<tr>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700 dark:text-slate-300">
						<button onclick={() => toggleSort('word')} class="inline-flex items-center gap-1 hover:text-blue-600 dark:hover:text-blue-400 {sortColumn === 'word' ? 'text-blue-600 dark:text-blue-400' : ''}">
							Word {#if sortColumn === 'word'}{@render iconChevron(sortDirection === 'asc')}{/if}
						</button>
					</th>
					<!-- w-px + whitespace-nowrap: the standard auto-layout-table trick
					     for "shrink this column to its content's width, and give any
					     leftover width to the other column(s) instead" - a table cell
					     can never shrink below its content's own minimum width even
					     with an explicit width this small, but it also won't claim any
					     of the table's extra distributable space the way an
					     unconstrained column does. That's what lets this column sit
					     snugly around the dots (not stretched to the far edge on its
					     own text-align) while still ending up flush against the
					     table's right edge, since Word is the only column left to
					     absorb the rest of the table's width. -->
					<th class="w-px whitespace-nowrap text-center px-4 py-3 text-sm font-medium text-gray-700 dark:text-slate-300">
						<button onclick={() => toggleSort('familiarity')} class="inline-flex items-center gap-1 hover:text-blue-600 dark:hover:text-blue-400 {sortColumn === 'familiarity' ? 'text-blue-600 dark:text-blue-400' : ''}">
							Familiarity {#if sortColumn === 'familiarity'}{@render iconChevron(sortDirection === 'asc')}{/if}
						</button>
					</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100 dark:divide-slate-800">
				{#each filtered() as w (w.id)}
					<tr class="cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800" onclick={(e) => handleRowClick(e, w.word)}>
						<td class="px-4 py-3 text-lg font-medium">{w.word}</td>
						<td class="w-px whitespace-nowrap px-4 py-3">
							<FamiliarityDots
								familiarity={w.familiarity}
								disabled={updatingWord === w.word}
								dotSize="w-4 h-4"
								onSetFamiliarity={(score) => setFamiliarity(w.word, score)}
							/>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

	<WordDetailModal
		word={selectedWordForPanel}
		context={panelContext}
		onClose={() => selectedWordForPanel = null}
		onFamiliarityChanged={(familiarity) => {
			if (!selectedWordForPanel) return;
			if (familiarity === null) {
				words = words.filter((w) => w.word !== selectedWordForPanel);
			} else {
				words = words.map((w) => w.word === selectedWordForPanel ? { ...w, familiarity } : w);
			}
		}}
		onGarbageMarked={() => {
			if (!selectedWordForPanel) return;
			words = words.filter((w) => w.word !== selectedWordForPanel);
		}}
	/>
</div>
