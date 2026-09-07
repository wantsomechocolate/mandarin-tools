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
	const FILTER_STORAGE_KEY = 'mandarin_tools_starred_words_filters';

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

	// No more `note` field - that used to live here (a StarredWord-only
	// column, with its own "+ Note"/"Edit note" UI on this page), but has
	// been generalized into its own standalone WordNote concept, editable
	// from the info pane for any word regardless of starred status, and
	// browsable on its own "Notes" profile tab. See WordNote's docstring,
	// models.py.
	interface StarredWordRow {
		id: number;
		word: string;
	}

	let rows: StarredWordRow[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state(storedFilters.search ?? '');
	let saving: string | null = $state(null);

	let newWord = $state('');
	let adding = $state(false);

	// Same tri-state toggle/plain-codepoint-comparison shape as Known/User
	// Words' identical toggleSort - only "word" is sortable here (the star
	// column is constant across every row on this page by definition).
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
			rows = await api.listStarredWords() as StarredWordRow[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load starred words';
		} finally {
			loading = false;
		}
	});

	const filtered = $derived(() => {
		const q = search.trim();
		let list = q ? rows.filter((r) => r.word.includes(q)) : rows;
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

	// Same click-passthrough pattern as Known/User Words - clicking anywhere
	// on the row opens the panel, unless the click landed on the star button.
	function handleRowClick(event: MouseEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		selectedWordForPanel = word;
	}

	async function remove(word: string) {
		saving = word;
		try {
			await api.deleteStarredWord(word);
			rows = rows.filter((r) => r.word !== word);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to unstar';
		} finally {
			saving = null;
		}
	}

	// Reactive so the form can warn before submission, same as the other
	// profile tabs' add-forms now do - see notes/+page.svelte's addNote for
	// the original version of this pattern. Nothing to "update" here (star
	// status is a plain boolean, not a value like Known Words' familiarity),
	// so a duplicate stays blocked - the warning just explains why.
	const existingStarredWord = $derived(rows.find((r) => r.word === newWord.trim()) ?? null);

	async function addWord() {
		const word = newWord.trim();
		if (!word || existingStarredWord) return;
		adding = true;
		try {
			const created = await api.createStarredWord(word) as StarredWordRow;
			rows = [created, ...rows];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to star word';
		} finally {
			adding = false;
		}
	}
</script>

<!-- Same filled/outline star as analyze/[id]'s own row/card star toggle
     (see its docstring there) - kept as its own copy per this codebase's
     per-file icon-snippet convention. Always rendered filled(true) here -
     every row on this page is, by definition, currently starred. -->
{#snippet iconStar(filled: boolean)}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.3" stroke-linejoin="round">
		<path d="M10 2.5l2.2 4.6 5 .7-3.6 3.6.85 5-4.45-2.4-4.45 2.4.85-5-3.6-3.6 5-.7L10 2.5Z" />
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

<svelte:head><title>Starred Words - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- Global per user+word, no scoping - same reasoning as KnownWord (see
     StarredWord's docstring, models.py). -->
<div class="bg-white rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 mb-2">Star a word</p>
	<div class="flex flex-wrap items-center gap-2">
		<input
			type="text"
			bind:value={newWord}
			placeholder="Chinese word..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
			onkeydown={(e) => { if (e.key === 'Enter') addWord(); }}
		/>
		<button
			onclick={addWord}
			disabled={!newWord.trim() || adding || !!existingStarredWord}
			class="text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
		>
			{adding ? 'Adding...' : existingStarredWord ? 'Already starred' : 'Add'}
		</button>
	</div>
	{#if existingStarredWord}
		<p class="text-xs text-amber-600 mt-2">
			"{existingStarredWord.word}" is already starred.
		</p>
	{/if}
</div>

<div class="flex items-center justify-between mb-3 gap-3 flex-wrap">
	<input
		type="search"
		bind:value={search}
		placeholder="Search words..."
		class="border border-gray-300 rounded px-2 py-1 text-sm w-56"
	/>
	<span class="text-sm text-gray-400">{filtered().length} of {rows.length} words</span>
</div>

<!-- Shared flex row with the panel below (lg and up) - same mechanism as
     the analysis results page: the panel's own backdrop wrapper collapses
     to `display: contents` at `lg`, so its child joins this row as a
     sticky-positioned sibling instead of floating as a modal. -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 p-4">Loading...</p>
	{:else if rows.length === 0}
		<p class="text-gray-500 p-4">No starred words yet - star one above, or from any analysis.</p>
	{:else if filtered().length === 0}
		<p class="text-gray-500 p-4">No words match.</p>
	{:else}
		<table class="w-full">
			<thead class="bg-gray-50 border-b border-gray-200">
				<tr>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">
						<button onclick={() => toggleSort('word')} class="inline-flex items-center gap-1 hover:text-blue-600 {sortColumn === 'word' ? 'text-blue-600' : ''}">
							Word {#if sortColumn === 'word'}{@render iconChevron(sortDirection === 'asc')}{/if}
						</button>
					</th>
					<th class="w-px whitespace-nowrap text-center px-4 py-3 text-sm font-medium text-gray-700">Starred</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100">
				{#each filtered() as row (row.id)}
					<tr class="cursor-pointer hover:bg-gray-50" onclick={(e) => handleRowClick(e, row.word)}>
						<td class="px-4 py-3">
							<p class="text-lg font-medium">{row.word}</p>
						</td>
						<td class="w-px whitespace-nowrap px-4 py-3 text-center">
							<button
								onclick={() => remove(row.word)}
								disabled={saving === row.word}
								class="p-1 rounded text-amber-500 hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
								title="Starred — click to unstar"
								aria-label="Starred — click to unstar"
							>
								{@render iconStar(true)}
							</button>
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
		onGarbageMarked={() => {
			if (!selectedWordForPanel) return;
			rows = rows.filter((r) => r.word !== selectedWordForPanel);
		}}
	/>
</div>
