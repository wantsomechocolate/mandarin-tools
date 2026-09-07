<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import WordDetailModal from '$lib/components/WordDetailModal.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';

	// Persisted filter preferences - see known-words/+page.svelte's own
	// FILTER_STORAGE_KEY comment for the full pattern and why search is
	// included here (unlike analyze/[id]'s).
	const FILTER_STORAGE_KEY = 'mandarin_tools_garbage_words_filters';

	interface StoredFilters {
		search: string;
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

	// Global list page - see the matching comment in known-words/+page.svelte.
	const panelContext: WordDetailContext = { type: 'global' };
	let selectedWordForPanel: string | null = $state(null);

	interface GarbageWordRow {
		id: number;
		word: string;
		is_override: boolean;
		user_id: number | null;
	}

	let raw: GarbageWordRow[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state(storedFilters.search ?? '');
	let updating: string | null = $state(null);

	let newWord = $state('');
	let adding = $state(false);

	// Only one sortable column here (unlike Known/User Words' word+familiarity
	// pair), but the same tri-state toggle/plain-codepoint-comparison shape
	// as those pages, for consistency - see their identical toggleSort for
	// why codepoint, not localeCompare.
	type SortColumn = 'word' | null;
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

	// Persist filter preferences on every change - see known-words'
	// identical effect for the reasoning.
	$effect(() => {
		if (!browser) return;
		try {
			const toStore: StoredFilters = { search, sortColumn, sortDirection };
			localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(toStore));
		} catch {
			// e.g. storage disabled/full - filters just won't persist, no need to surface an error
		}
	});

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			raw = await api.listGarbageWords() as GarbageWordRow[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load garbage words';
		} finally {
			loading = false;
		}
	});

	// Mirrors service.get_user_garbage_words' resolution (garbage - overrides)
	// client-side, same math already used by the analysis-results page's own
	// garbageWords Set (see its onMount) - the raw list mixes system
	// defaults, a user's own additions, and override rows that cancel one of
	// those out, all as separate rows for the same word.
	const resolvedGarbage = $derived(() => {
		const overrideWords = new Set(raw.filter((g) => g.is_override).map((g) => g.word));
		const seen = new Set<string>();
		const list: { word: string; systemDefault: boolean }[] = [];
		for (const g of raw) {
			if (g.is_override || overrideWords.has(g.word) || seen.has(g.word)) continue;
			seen.add(g.word);
			list.push({ word: g.word, systemDefault: g.user_id === null });
		}
		return list;
	});

	// Words where the user has an override row cancelling out a garbage
	// marking (system-default or their own) - "not garbage, despite
	// whatever would otherwise mark it" (see GarbageWord.is_override /
	// unmark_garbage_word, router.py).
	const excluded = $derived(() => {
		return raw.filter((g) => g.is_override).map((g) => g.word);
	});

	const filteredGarbage = $derived(() => {
		const q = search.trim();
		let list = q ? resolvedGarbage().filter((g) => g.word.includes(q)) : resolvedGarbage();
		if (sortColumn === 'word') {
			list = [...list].sort((a, b) => {
				// Plain codepoint comparison, not localeCompare with a 'zh'
				// locale - see the results page's identical reasoning, CLAUDE.md.
				const cmp = a.word < b.word ? -1 : a.word > b.word ? 1 : 0;
				return sortDirection === 'desc' ? -cmp : cmp;
			});
		}
		return list;
	});

	// Same click-passthrough pattern as Known Words/User Words - clicking
	// anywhere on the row opens the panel, unless the click landed on an
	// actual interactive element (the un-mark icon button, here).
	function handleRowClick(event: MouseEvent | KeyboardEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		selectedWordForPanel = word;
	}

	// unmark_garbage_word (router.py) does one of two different things
	// server-side depending on what's already there: deletes the user's own
	// plain row if they have one, or - only when the word is garbage purely
	// via a system default - adds a *new* override row instead. The old
	// blanket `raw.filter(word matches && !is_override)` patch assumed only
	// one non-override row could ever exist per word, which is true right
	// after a fresh unmark - but a word can end up with BOTH a system-
	// default row (is_override:false, user_id:null) AND this user's own
	// flipped-back row (is_override:false, user_id:theirs) at once, via the
	// "Re-mark as garbage" flow below (or the same flip reachable from the
	// add form above) - found live while testing that flow. In that state
	// the blanket filter deleted the system-default row too, even though
	// only the user's own row was actually removed server-side, making the
	// word vanish from the list entirely instead of falling back to "still
	// garbage via the system default."
	async function unmark(word: string) {
		updating = word;
		try {
			await api.unmarkGarbageWord(word);
			const ownPlainRow = raw.find((g) => g.word === word && !g.is_override && g.user_id !== null);
			if (ownPlainRow) {
				// Backend's first branch: that exact row was deleted.
				raw = raw.filter((g) => g.id !== ownPlainRow.id);
			} else {
				// Backend's second branch: a new override row was created,
				// server-side, with an id this response doesn't hand back -
				// simplest correct fix is just re-fetching rather than
				// fabricating a row.
				raw = await api.listGarbageWords() as GarbageWordRow[];
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to un-mark';
		} finally {
			updating = null;
		}
	}

	async function remark(word: string) {
		updating = word;
		try {
			// Flips an existing override row back to is_override=false rather
			// than erroring as a duplicate - see create_garbage_word's
			// docstring (router.py).
			await api.createGarbageWord(word, false);
			raw = raw.map((g) => g.word === word && g.is_override ? { ...g, is_override: false } : g);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to re-mark as garbage';
		} finally {
			updating = null;
		}
	}

	// Two different situations, not one - see the template's two separate
	// messages. A word already *actively* garbage has nothing useful left
	// for this form to do (blocked). A word that's currently *excluded*
	// (an override row cancelling out a marking - see GarbageWord.is_override,
	// models.py) is a different case: re-adding it here is the same
	// legitimate "mark it again" flip create_garbage_word already supports
	// server-side (see its docstring, router.py) - the same action as this
	// page's own "Re-mark as garbage" button below, just reachable from the
	// add form too. Not blocked - only flagged, so the user knows what it'll
	// do. The two are mutually exclusive by construction (resolvedGarbage
	// already excludes override rows), so only one message can show.
	const existingActiveGarbage = $derived(resolvedGarbage().find((g) => g.word === newWord.trim()) ?? null);
	const isCurrentlyExcluded = $derived(excluded().includes(newWord.trim()));

	async function addWord() {
		const word = newWord.trim();
		if (!word || existingActiveGarbage) return;
		adding = true;
		try {
			const created = await api.createGarbageWord(word, false) as GarbageWordRow;
			// The "re-mark an excluded word" case (isCurrentlyExcluded above)
			// returns the SAME row, flipped (create_garbage_word's docstring,
			// router.py) - same id, is_override now false. Naively prepending
			// left the old (stale, still is_override:true) copy of that same
			// row sitting in `raw` too, and resolvedGarbage's own "any override
			// row for this word means excluded" rule (see its comment above)
			// then kept treating the word as excluded even after the flip -
			// found live while testing this exact flow. Dropping any existing
			// row with the same id first fixes both this case and is a no-op
			// for a genuinely new word (nothing to drop).
			raw = [created, ...raw.filter((g) => g.id !== created.id)];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add';
		} finally {
			adding = false;
		}
	}
</script>

<!-- Same circle-with-diagonal-slash "no-entry" glyph as analyze/[id]'s own
     iconTrash (that name is a misnomer there too - see its docstring) used
     for the results-table garbage toggle. Kept as its own copy per this
     codebase's per-file icon-snippet convention. -->
{#snippet iconGarbage()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
		<circle cx="10" cy="10" r="7.25" />
		<path d="M5.15 14.85l9.7-9.7" />
	</svg>
{/snippet}

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

<svelte:head><title>Garbage Words - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- Garbage words are never excluded from analysis results server-side -
     they're persisted like any other word and just annotated/hidden by
     default client-side (see WordResult.is_garbage's docstring, schemas.py).
     This page manages the underlying marking, not any one analysis's view
     of it. -->
<div class="bg-white rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 mb-2">Mark a word as garbage</p>
	<div class="flex items-center gap-2">
		<input
			type="text"
			bind:value={newWord}
			placeholder="Word or symbol..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
			onkeydown={(e) => { if (e.key === 'Enter') addWord(); }}
		/>
		<button
			onclick={addWord}
			disabled={!newWord.trim() || adding || !!existingActiveGarbage}
			class="text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
		>
			{adding ? 'Adding...' : existingActiveGarbage ? 'Already marked' : isCurrentlyExcluded ? 'Re-mark as garbage' : 'Add'}
		</button>
	</div>
	{#if existingActiveGarbage}
		<p class="text-xs text-amber-600 mt-2">
			"{existingActiveGarbage.word}" is already marked as garbage.
		</p>
	{:else if isCurrentlyExcluded}
		<p class="text-xs text-blue-600 mt-2">
			"{newWord.trim()}" is currently excluded from garbage - adding it here will re-mark it as garbage (same as "Re-mark as garbage" below).
		</p>
	{/if}
</div>

<div class="flex items-center justify-between mb-3 gap-3 flex-wrap">
	<input
		type="search"
		bind:value={search}
		placeholder="Search words..."
		class="border border-gray-300 rounded px-2 py-1 text-sm w-48"
	/>
	<span class="text-sm text-gray-400">{filteredGarbage().length} of {resolvedGarbage().length} words</span>
</div>

<!-- Shared flex row with the panel below (lg and up) - same mechanism as
     the analysis results page: the panel's own backdrop wrapper collapses
     to `display: contents` at `lg`, so its child joins this row as a
     sticky-positioned sibling instead of floating as a modal. This page was
     missing this wrapper (WordDetailModal was still rendered, just as a
     block child at the bottom of the page instead of the docked panel it's
     everywhere else - hence rows appearing not to open anything). -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white rounded-lg shadow-sm overflow-hidden mb-6">
	{#if loading}
		<p class="text-gray-500 p-4">Loading...</p>
	{:else if resolvedGarbage().length === 0}
		<p class="text-gray-500 p-4">No garbage words currently marked.</p>
	{:else if filteredGarbage().length === 0}
		<p class="text-gray-500 p-4">No words match.</p>
	{:else}
		<div class="bg-gray-50 border-b border-gray-200 px-4 py-3">
			<button onclick={() => toggleSort('word')} class="inline-flex items-center gap-1 text-sm font-medium text-gray-700 hover:text-blue-600 {sortColumn === 'word' ? 'text-blue-600' : ''}">
				Word {#if sortColumn === 'word'}{@render iconChevron(sortDirection === 'asc')}{/if}
			</button>
		</div>
		<div class="divide-y divide-gray-100">
			{#each filteredGarbage() as g (g.word)}
				<div
					role="button"
					tabindex="0"
					onclick={(e) => handleRowClick(e, g.word)}
					onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleRowClick(e, g.word); } }}
					class="flex items-center justify-between px-4 py-2.5 cursor-pointer hover:bg-gray-50"
				>
					<div class="flex items-center gap-2">
						<span class="text-base">{g.word}</span>
						{#if g.systemDefault}
							<span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">system default</span>
						{/if}
					</div>
					<button
						onclick={() => unmark(g.word)}
						disabled={updating === g.word}
						class="p-1 rounded text-red-600 hover:text-red-800 hover:bg-red-50 disabled:opacity-50"
						title="Marked as garbage — click to unmark"
						aria-label="Marked as garbage — click to unmark"
					>
						{@render iconGarbage()}
					</button>
				</div>
			{/each}
		</div>
	{/if}
</div>

	<!-- No onGarbageMarked wired here (unlike analyze/[id]/known-words'-sibling
	     pages that track garbage state) - it only ever fires on a false->true
	     transition, and every word opened from this page's own rows is already
	     true, so it could never meaningfully fire. There's no callback at all
	     for the reverse (true->false) transition on WordDetailPanel today, so
	     un-marking a word from deep inside the panel (rather than this row's
	     own icon button, which does patch `raw` directly) leaves this list
	     stale until reload - the same accepted, documented trade-off the other
	     profile list pages already have for edits made outside their own
	     wired callbacks. -->
	<WordDetailModal
		word={selectedWordForPanel}
		context={panelContext}
		onClose={() => selectedWordForPanel = null}
	/>
</div>

{#if excluded().length > 0}
	<h2 class="text-sm font-semibold text-gray-600 mb-2">Excluded from garbage</h2>
	<p class="text-xs text-gray-400 mb-2">
		Words you've explicitly said aren't garbage, overriding a system default or an earlier marking.
	</p>
	<div class="bg-white rounded-lg shadow-sm overflow-hidden">
		<div class="divide-y divide-gray-100">
			{#each excluded() as word}
				<div class="flex items-center justify-between px-4 py-2.5">
					<span class="text-base">{word}</span>
					<button
						onclick={() => remark(word)}
						disabled={updating === word}
						class="text-xs text-blue-600 hover:text-blue-800 disabled:opacity-50"
					>
						Re-mark as garbage
					</button>
				</div>
			{/each}
		</div>
	</div>
{/if}
