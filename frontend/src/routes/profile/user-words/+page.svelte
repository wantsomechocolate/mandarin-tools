<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import { familiarityLabel, familiarityColor } from '$lib/wordDisplay';
	import WordDetailPanel from '$lib/components/WordDetailPanel.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';

	// Global list page - see the matching comment in known-words/+page.svelte.
	const panelContext: WordDetailContext = { type: 'global' };
	let selectedWordForPanel: string | null = $state(null);

	// Raw per-scope-entry rows from the API (a word can have up to 3: global/
	// text/analysis - see WordDetail.user_word_entries' docstring, schemas.py).
	// This page only ever reads `word` and the two scope columns off these -
	// the rest of each entry's detail (pronunciation/meaning/notes/
	// affects_dag) lives exclusively in the panel now, not duplicated here.
	interface UserWordRawRow {
		word: string;
		scope_analysis_id: number | null;
		scope_input_text_id: number | null;
	}

	type Scope = 'global' | 'text' | 'analysis';

	// One row per distinct word, not per scope-entry - same 3-column shape
	// (word/familiarity/actions) as Known Words, for a consistent look
	// across the profile tabs. `scopes` is display-only (not sortable) -
	// full per-scope detail lives in the panel, opened via the info icon or
	// a row click.
	interface WordRow {
		word: string;
		familiarity: number | null;
		scopes: Set<Scope>;
	}

	let rawRows: UserWordRawRow[] = $state([]);
	let knownWords: Record<string, number | null> = $state({});
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let scopeFilter: 'all' | Scope = $state('all');

	let newWord = $state('');
	let adding = $state(false);

	type SortColumn = 'word' | 'familiarity' | null;
	let sortColumn: SortColumn = $state(null);
	let sortDirection: 'asc' | 'desc' = $state('asc');

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

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			const [uwData, kwData] = await Promise.all([
				api.listAllUserWords() as Promise<UserWordRawRow[]>,
				api.listKnownWords() as Promise<{ word: string; familiarity: number | null }[]>,
			]);
			rawRows = uwData;
			knownWords = Object.fromEntries(kwData.map((k) => [k.word, k.familiarity]));
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load user words';
		} finally {
			loading = false;
		}
	});

	function scopeOfRow(row: UserWordRawRow): Scope {
		if (row.scope_analysis_id != null) return 'analysis';
		if (row.scope_input_text_id != null) return 'text';
		return 'global';
	}

	// Collapses the raw per-entry rows down to one WordRow per distinct word
	// - the whole point of this redesign (this list used to show one row per
	// word/scope combination).
	const words = $derived(() => {
		const byWord = new Map<string, WordRow>();
		for (const row of rawRows) {
			let w = byWord.get(row.word);
			if (!w) {
				w = { word: row.word, familiarity: knownWords[row.word] ?? null, scopes: new Set() };
				byWord.set(row.word, w);
			}
			w.scopes.add(scopeOfRow(row));
		}
		return [...byWord.values()];
	});

	const filtered = $derived(() => {
		const q = search.trim();
		let list = words();
		if (q) list = list.filter((w) => w.word.includes(q));
		const scope = scopeFilter;
		if (scope !== 'all') list = list.filter((w) => w.scopes.has(scope));
		if (sortColumn) {
			list = [...list].sort((a, b) => {
				// Plain codepoint comparison for word - not localeCompare with a
				// 'zh' locale, which sorts by pinyin (see the results page's
				// identical reasoning, CLAUDE.md).
				const cmp = sortColumn === 'word'
					? (a.word < b.word ? -1 : a.word > b.word ? 1 : 0)
					: (a.familiarity ?? -1) - (b.familiarity ?? -1);
				return sortDirection === 'desc' ? -cmp : cmp;
			});
		}
		return list;
	});

	// Same click-passthrough pattern as Known Words/the analysis results
	// page (handleRowClick) - clicking anywhere on the row opens the panel,
	// unless the click landed on an actual interactive element.
	function handleRowClick(event: MouseEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		selectedWordForPanel = word;
	}

	// Always global - a new entry from this page has no "current text/
	// analysis" to scope to. Text/analysis-scoped entries are added from
	// within that specific analysis's word-detail panel instead.
	async function addWord() {
		const word = newWord.trim();
		if (!word || words().some((w) => w.word === word)) return;
		adding = true;
		try {
			const created = await api.upsertUserWordDetail(word, { affects_dag: true }, { scope: 'global' }) as UserWordRawRow;
			rawRows = [created, ...rawRows];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add word';
		} finally {
			adding = false;
		}
	}

	// Fired by the panel after any UserWord mutation, with that word's
	// fresh full entries list - replace this word's raw rows wholesale
	// (rather than trying to patch individual scope rows) so an add/edit/
	// delete inside the panel is reflected here immediately, including the
	// word disappearing entirely once its last entry is removed.
	function handleUserWordEntriesChanged(entries: { scope: Scope; analysis_id: number | null; text_id: number | null }[]) {
		if (!selectedWordForPanel) return;
		const word = selectedWordForPanel;
		const nextForWord: UserWordRawRow[] = entries.map((e) => ({
			word,
			scope_analysis_id: e.scope === 'analysis' ? e.analysis_id : null,
			scope_input_text_id: e.scope === 'text' ? e.text_id : null,
		}));
		rawRows = [...rawRows.filter((r) => r.word !== word), ...nextForWord];
	}
</script>

<svelte:head><title>User Words - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- Unlike Known Words, a word can have several simultaneous entries here
     (global plus a one-off override for a specific text/analysis) - see
     WordDetail.user_word_entries' docstring (schemas.py). This list shows
     one row per word regardless (matching Known Words' shape) - open the
     panel for the full per-scope breakdown. -->
<div class="bg-white rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 mb-1">Add a word (global)</p>
	<p class="text-xs text-gray-400 mb-2">
		New entries here are always global. To scope one to a specific text or analysis, add it from that analysis's word panel instead.
	</p>
	<div class="flex items-center gap-2">
		<input
			type="text"
			bind:value={newWord}
			placeholder="Chinese word..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
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
	<span class="text-sm text-gray-400">{filtered().length} of {words().length} words</span>
</div>

<!-- Shared flex row with the panel below (lg and up) - same mechanism as
     the analysis results page: the panel's own backdrop wrapper collapses
     to `display: contents` at `lg`, so its child joins this row as a
     sticky-positioned sibling instead of floating as a modal. -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 p-4">Loading...</p>
	{:else if words().length === 0}
		<p class="text-gray-500 p-4">No user words yet - add one above, or from any analysis's word panel.</p>
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
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">
						<button onclick={() => toggleSort('familiarity')} class="hover:text-blue-600 {sortColumn === 'familiarity' ? 'text-blue-600' : ''}">
							Familiarity {#if sortColumn === 'familiarity'}({sortDirection}){/if}
						</button>
					</th>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100">
				{#each filtered() as w (w.word)}
					<tr class="cursor-pointer hover:bg-gray-50" onclick={(e) => handleRowClick(e, w.word)}>
						<td class="px-4 py-3 text-lg font-medium">{w.word}</td>
						<td class="px-4 py-3">
							<span class="text-xs px-2 py-1 rounded-full {familiarityColor(w.familiarity)}">
								{familiarityLabel(w.familiarity)}
							</span>
						</td>
						<td class="px-4 py-3">
							<button
								onclick={() => selectedWordForPanel = w.word}
								class="p-1 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50"
								title="View details"
								aria-label="View details"
							>
								<svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
									<circle cx="10" cy="5.3" r="1.7" />
									<rect x="8.2" y="8.6" width="3.6" height="7.6" rx="1.8" />
								</svg>
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

{#if selectedWordForPanel}
	<div
		class="fixed inset-0 z-40 flex items-end justify-center bg-black/30 lg:contents"
		onclick={() => selectedWordForPanel = null}
		role="presentation"
	>
		<div class="self-start lg:sticky lg:top-4" onclick={(e) => e.stopPropagation()} role="presentation">
			<WordDetailPanel
				word={selectedWordForPanel}
				context={panelContext}
				onClose={() => selectedWordForPanel = null}
				onUserWordEntriesChanged={handleUserWordEntriesChanged}
				onFamiliarityChanged={(familiarity) => {
					if (!selectedWordForPanel) return;
					knownWords = { ...knownWords, [selectedWordForPanel]: familiarity };
				}}
				onGarbageMarked={() => {
					if (!selectedWordForPanel) return;
					rawRows = rawRows.filter((r) => r.word !== selectedWordForPanel);
				}}
			/>
		</div>
	</div>
{/if}
</div>
