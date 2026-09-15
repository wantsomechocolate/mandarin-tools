<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import WordDetailModal from '$lib/components/WordDetailModal.svelte';
	import { entryLabel, type WordDetailContext } from '$lib/wordDetailContext';
	import { saveOpenWordPanel, loadOpenWordPanel } from '$lib/panelWordPersistence';
	import { trackScrollPosition, restoreScrollPosition } from '$lib/scrollPersistence';
	import { findNeighborWord } from '$lib/wordListSwipe';

	// Persisted filter preferences - see known-words/+page.svelte's own
	// FILTER_STORAGE_KEY comment for the full pattern and why search is
	// included here (unlike analyze/[id]'s).
	const FILTER_STORAGE_KEY = 'mandarin_tools_hidden_words_filters';

	interface StoredFilters {
		search: string;
		scopeFilter: 'all' | Scope;
		sortDirection: 'asc' | 'desc' | null;
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
	// See panelWordPersistence.ts's docstring - recovers which word's panel
	// was open across a mobile browser's involuntary page reload.
	let selectedWordForPanel: string | null = $state(loadOpenWordPanel());
	$effect(() => {
		saveOpenWordPanel(selectedWordForPanel);
	});

	type Scope = 'global' | 'text' | 'analysis';

	// One raw row per WordVisibility entry (see list_word_visibility's
	// docstring, router.py) - same shape as WordDetailPanel's own
	// VisibilityEntry, plus `word`, so entryLabel (wordDetailContext.ts) works
	// unchanged on these rows too.
	interface VisibilityRow {
		id: number;
		word: string;
		scope: Scope;
		text_id: number | null;
		text_title: string | null;
		analysis_id: number | null;
		analysis_created_at: string | null;
		hidden: boolean;
	}

	// One row per distinct word - a word can have several simultaneous
	// WordVisibility entries (a global one plus a text/analysis override
	// cancelling it back out - see WordVisibility's docstring, models.py),
	// same "collapse to one row per word, full detail lives in the badges/
	// panel" shape as the User Words page.
	interface WordRow {
		word: string;
		entries: VisibilityRow[];
	}

	let raw: VisibilityRow[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	// Scroll position across a page reload - see scrollPersistence.ts's
	// docstring. Restoring waits for `loading` to flip false, since
	// scrolling to a saved position makes no sense before the list it
	// depends on has arrived.
	$effect(() => trackScrollPosition(location.pathname));
	let scrollRestored = false;
	$effect(() => {
		if (loading || scrollRestored) return;
		scrollRestored = true;
		restoreScrollPosition(location.pathname);
	});
	let search = $state(storedFilters.search ?? '');
	let scopeFilter: 'all' | Scope = $state(storedFilters.scopeFilter ?? 'all');

	let newWord = $state('');
	let hiding = $state(false);

	// Only one sortable column (word) - same tri-state toggle/plain-codepoint-
	// comparison shape as every other list here, but there's no second
	// column to sort by: "hidden" isn't a single value per word the way
	// familiarity/note text are, since a word can be hidden at one scope and
	// shown at another simultaneously (the whole point of this page).
	let sortDirection: 'asc' | 'desc' | null = $state(storedFilters.sortDirection ?? null);

	function toggleSort() {
		if (sortDirection === null) sortDirection = 'asc';
		else if (sortDirection === 'asc') sortDirection = 'desc';
		else sortDirection = null;
	}

	// Persist filter preferences on every change - see known-words'
	// identical effect for the reasoning.
	$effect(() => {
		if (!browser) return;
		try {
			const toStore: StoredFilters = { search, scopeFilter, sortDirection };
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
			raw = await api.listWordVisibility() as VisibilityRow[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load hidden words';
		} finally {
			loading = false;
		}
	});

	const SCOPE_ORDER: Scope[] = ['global', 'text', 'analysis'];

	// Collapses the raw per-entry rows down to one WordRow per distinct word,
	// each entry's own scope/hidden value intact (unlike the User Words page,
	// existence alone isn't enough here - see the WordRow docstring above).
	// Entries within a word are sorted to the canonical Global -> Text ->
	// Analysis order (same order the results-table badge fan uses, CLAUDE.md)
	// for a stable, predictable display order.
	const words = $derived(() => {
		const byWord = new Map<string, WordRow>();
		for (const row of raw) {
			let w = byWord.get(row.word);
			if (!w) {
				w = { word: row.word, entries: [] };
				byWord.set(row.word, w);
			}
			w.entries.push(row);
		}
		for (const w of byWord.values()) {
			w.entries.sort((a, b) => SCOPE_ORDER.indexOf(a.scope) - SCOPE_ORDER.indexOf(b.scope));
		}
		return [...byWord.values()];
	});

	const filtered = $derived(() => {
		const q = search.trim();
		let list = words();
		if (q) list = list.filter((w) => w.word.includes(q));
		const scope = scopeFilter;
		if (scope !== 'all') list = list.filter((w) => w.entries.some((e) => e.scope === scope));
		if (sortDirection) {
			list = [...list].sort((a, b) => {
				// Plain codepoint comparison - not localeCompare with a 'zh'
				// locale, which sorts by pinyin (see the results page's
				// identical reasoning, CLAUDE.md).
				const cmp = a.word < b.word ? -1 : a.word > b.word ? 1 : 0;
				return sortDirection === 'desc' ? -cmp : cmp;
			});
		}
		return list;
	});

	// Same click-passthrough pattern as every other profile list page -
	// clicking anywhere on the row opens the panel, unless the click landed
	// on an actual interactive element.
	function handleRowClick(event: MouseEvent | KeyboardEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		selectedWordForPanel = word;
	}

	// Specifically a *global* entry, not "this word appears anywhere in
	// words()" - a word with only a text/analysis-scoped override has no
	// global row yet, and adding one here is a legitimate, additive action,
	// not a duplicate (same reasoning as User Words' existingGlobalUserWord).
	const existingGlobalEntry = $derived(
		raw.find((r) => r.word === newWord.trim() && r.scope === 'global') ?? null
	);

	// Always global, and always sets hidden=true - text/analysis-scoped
	// overrides are added from within that specific text/analysis's own
	// word-detail panel instead (same division of labor as User Words' own
	// add form). Unlike UserWordUpsert, WordVisibilityUpsert has no partial-
	// update ambiguity to worry about (see its docstring, schemas.py) -
	// `hidden` is always required and always written, so re-using this on an
	// existing global entry safely flips it to hidden rather than risking
	// clobbering unrelated fields the way User Words' form has to avoid.
	async function hideWord() {
		const word = newWord.trim();
		if (!word || existingGlobalEntry?.hidden) return;
		hiding = true;
		try {
			const updated = await api.upsertWordVisibility(word, true, { scope: 'global' }) as { id: number; word: string; hidden: boolean };
			const entry: VisibilityRow = {
				id: updated.id, word: updated.word, hidden: updated.hidden,
				scope: 'global', text_id: null, text_title: null, analysis_id: null, analysis_created_at: null,
			};
			raw = [entry, ...raw.filter((r) => !(r.word === word && r.scope === 'global'))];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to hide word';
		} finally {
			hiding = false;
		}
	}

	// Mobile swipe-to-navigate (WordDetailModal's onSwipeNext/onSwipePrevious)
	// - see findNeighborWord's docstring, wordListSwipe.ts, for why this
	// page just re-reads its own live filtered() array rather than freezing
	// a session list the way analyze/[id]'s own swipeToWord does.
	function swipeToWord(direction: 'next' | 'prev') {
		if (!selectedWordForPanel) return;
		const target = findNeighborWord(filtered(), selectedWordForPanel, direction);
		if (target) selectedWordForPanel = target;
	}

	// Fired by the panel after any WordVisibility mutation, with the word's
	// fresh full entries list - replace this word's raw rows wholesale
	// (rather than trying to patch individual scope rows) so an add/edit/
	// remove inside the panel is reflected here immediately, same pattern as
	// User Words' own handleUserWordEntriesChanged.
	function handleVisibilityEntriesChanged(entries: { id: number; scope: Scope; text_id: number | null; text_title: string | null; analysis_id: number | null; analysis_created_at: string | null; hidden: boolean }[]) {
		if (!selectedWordForPanel) return;
		const word = selectedWordForPanel;
		const nextForWord: VisibilityRow[] = entries.map((e) => ({ ...e, word }));
		raw = [...raw.filter((r) => r.word !== word), ...nextForWord];
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

<svelte:head><title>Hidden Words - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- Unlike Known/User Words, a word here doesn't have one resolved state -
     it can be hidden globally and simultaneously overridden back to shown in
     one specific text (or vice versa) - see WordVisibility's docstring,
     models.py. This list shows every entry that exists per word, not a
     single merged answer - open the panel for the full editable breakdown. -->
<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 dark:text-slate-400 mb-1">Hide a word (global)</p>
	<p class="text-xs text-gray-400 dark:text-slate-500 mb-2">
		Hides the word from every analysis's results by default. To show it again in just one text or analysis, add that override from the word panel there instead.
	</p>
	<div class="flex items-center gap-2">
		<input
			type="text"
			bind:value={newWord}
			placeholder="Chinese word..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
			onkeydown={(e) => { if (e.key === 'Enter') hideWord(); }}
		/>
		<button
			onclick={hideWord}
			disabled={!newWord.trim() || hiding || !!existingGlobalEntry?.hidden}
			class="text-sm px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
		>
			{hiding ? 'Hiding...' : existingGlobalEntry?.hidden ? 'Already hidden' : 'Hide'}
		</button>
	</div>
	{#if existingGlobalEntry && !existingGlobalEntry.hidden}
		<p class="text-xs text-amber-600 mt-2">
			"{existingGlobalEntry.word}" has an explicit global "Shown" override - hiding it here will replace that.
		</p>
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
		<select bind:value={scopeFilter} class="border border-gray-300 rounded px-2 py-1 text-sm">
			<option value="all">All scopes</option>
			<option value="global">Has global entry</option>
			<option value="text">Has text-scoped entry</option>
			<option value="analysis">Has analysis-scoped entry</option>
		</select>
	</div>
	<span class="text-sm text-gray-400 dark:text-slate-500">{filtered().length} of {words().length} words</span>
</div>

<!-- Shared flex row with the panel below (lg and up) - same mechanism as
     the analysis results page: the panel's own backdrop wrapper collapses
     to `display: contents` at `lg`, so its child joins this row as a
     sticky-positioned sibling instead of floating as a modal. -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white dark:bg-slate-900 rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 dark:text-slate-400 p-4">Loading...</p>
	{:else if words().length === 0}
		<p class="text-gray-500 dark:text-slate-400 p-4">No hidden or overridden words yet - hide one above, or from any analysis's word panel.</p>
	{:else if filtered().length === 0}
		<p class="text-gray-500 dark:text-slate-400 p-4">No words match.</p>
	{:else}
		<div class="bg-gray-50 dark:bg-slate-950 border-b border-gray-200 dark:border-slate-800 px-4 py-3">
			<button onclick={toggleSort} class="inline-flex items-center gap-1 text-sm font-medium text-gray-700 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 {sortDirection ? 'text-blue-600 dark:text-blue-400' : ''}">
				Word {#if sortDirection}{@render iconChevron(sortDirection === 'asc')}{/if}
			</button>
		</div>
		<div class="divide-y divide-gray-100 dark:divide-slate-800">
			{#each filtered() as w (w.word)}
				<div
					role="button"
					tabindex="0"
					onclick={(e) => handleRowClick(e, w.word)}
					onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleRowClick(e, w.word); } }}
					class="flex items-center justify-between gap-3 px-4 py-2.5 cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800"
				>
					<span class="text-base shrink-0">{w.word}</span>
					<div class="flex items-center gap-1.5 flex-wrap justify-end">
						{#each w.entries as entry (entry.id)}
							<!-- Short scope word, not the full entryLabel (a text/
							     analysis title can be long) - the full label (e.g.
							     'Analysis of "..." (date)') is a tooltip instead, same
							     "compact by default, full detail on demand" trade-off
							     as the results-table badge fan's own title attribute. -->
							<span
								title={entryLabel(entry)}
								class="text-xs px-2 py-0.5 rounded-full {entry.hidden
									? 'bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-400'
									: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'}"
							>
								{entry.scope === 'global' ? 'Global' : entry.scope === 'text' ? 'Text' : 'Analysis'}: {entry.hidden ? 'Hidden' : 'Shown'}
							</span>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

	<WordDetailModal
		word={selectedWordForPanel}
		context={panelContext}
		onClose={() => selectedWordForPanel = null}
		onVisibilityEntriesChanged={handleVisibilityEntriesChanged}
		onGarbageMarked={() => {
			if (!selectedWordForPanel) return;
			raw = raw.filter((r) => r.word !== selectedWordForPanel);
		}}
		onSwipeNext={() => swipeToWord('next')}
		onSwipePrevious={() => swipeToWord('prev')}
	/>
</div>
