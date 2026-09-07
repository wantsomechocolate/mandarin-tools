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

	interface StarredWordRow {
		id: number;
		word: string;
		note: string | null;
	}

	let rows: StarredWordRow[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state(storedFilters.search ?? '');
	let saving: string | null = $state(null);

	let editingWord: string | null = $state(null);
	let noteDraft = $state('');

	let newWord = $state('');
	let newNote = $state('');
	let adding = $state(false);

	// Same tri-state toggle/plain-codepoint-comparison shape as Known/User
	// Words' identical toggleSort - only "word" is sortable here (note has
	// no natural sort order worth exposing, and the star column is constant
	// across every row on this page by definition).
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
		let list = q
			? rows.filter((r) => r.word.includes(q) || (r.note?.toLowerCase().includes(q.toLowerCase()) ?? false))
			: rows;
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
	// on the row opens the panel, unless the click landed on an actual
	// interactive element (the note input/Save/Cancel, or the star button).
	function handleRowClick(event: MouseEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		selectedWordForPanel = word;
	}

	function startEditing(row: StarredWordRow) {
		editingWord = row.word;
		noteDraft = row.note ?? '';
	}

	async function saveNote(word: string) {
		saving = word;
		try {
			const updated = await api.upsertStarredWord(word, noteDraft || null) as StarredWordRow;
			rows = rows.map((r) => r.word === word ? updated : r);
			editingWord = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to save note';
		} finally {
			saving = null;
		}
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

	async function addWord() {
		const word = newWord.trim();
		if (!word || rows.some((r) => r.word === word)) return;
		adding = true;
		try {
			const created = await api.createStarredWord(word, newNote || undefined) as StarredWordRow;
			rows = [created, ...rows];
			newWord = '';
			newNote = '';
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
		/>
		<input
			type="text"
			bind:value={newNote}
			placeholder="Note (optional)..."
			class="border border-gray-300 rounded px-2 py-1 text-sm flex-1 min-w-40"
			onkeydown={(e) => { if (e.key === 'Enter') addWord(); }}
		/>
		<button
			onclick={addWord}
			disabled={!newWord.trim() || adding}
			class="text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
		>
			{adding ? 'Adding...' : 'Add'}
		</button>
	</div>
</div>

<div class="flex items-center justify-between mb-3 gap-3 flex-wrap">
	<input
		type="search"
		bind:value={search}
		placeholder="Search words or notes..."
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
						<button onclick={() => toggleSort('word')} class="hover:text-blue-600 {sortColumn === 'word' ? 'text-blue-600' : ''}">
							Word {#if sortColumn === 'word'}({sortDirection}){/if}
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
							{#if editingWord === row.word}
								<div class="flex items-center gap-2 mt-1">
									<input
										type="text"
										bind:value={noteDraft}
										placeholder="Note..."
										class="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
										onkeydown={(e) => { if (e.key === 'Enter') saveNote(row.word); }}
									/>
									<button
										onclick={() => saveNote(row.word)}
										disabled={saving === row.word}
										class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
									>
										Save
									</button>
									<button
										onclick={() => editingWord = null}
										class="text-xs text-gray-500 hover:text-gray-700"
									>
										Cancel
									</button>
								</div>
							{:else}
								{#if row.note}
									<p class="text-sm text-gray-500 mt-0.5">{row.note}</p>
								{/if}
								<button onclick={() => startEditing(row)} class="text-xs text-blue-600 hover:text-blue-800 mt-0.5">
									{row.note ? 'Edit note' : '+ Note'}
								</button>
							{/if}
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
