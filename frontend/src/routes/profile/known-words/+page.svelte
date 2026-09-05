<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import { familiarityLabel, familiarityColor } from '$lib/wordDisplay';
	import WordDetailModal from '$lib/components/WordDetailModal.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';

	// Global list page - every word here is viewed with no text/analysis in
	// scope, so WordDetailPanel.svelte's UserWord/Visibility sections show
	// every entry read-only except the global one (see isEntryEditable,
	// wordDetailContext.ts - this falls out of the hierarchy rule with no
	// special case for "global page").
	const panelContext: WordDetailContext = { type: 'global' };
	let selectedWordForPanel: string | null = $state(null);

	interface KnownWord {
		id: number;
		word: string;
		familiarity: number | null;
	}

	let words: KnownWord[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let updatingWord: string | null = $state(null);

	let newWord = $state('');
	let newFamiliarity: number = $state(5);
	let adding = $state(false);

	// 'lte' is the primary use case (narrow down to less-familiar words);
	// 'eq' is a secondary, exact-match option - both share one value
	// selector rather than two independent controls, since only one mode
	// is ever active at a time.
	type FamiliarityFilterMode = 'all' | 'lte' | 'eq';
	let familiarityMode: FamiliarityFilterMode = $state('all');
	let familiarityValue = $state(5);

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
			words = await api.listKnownWords() as KnownWord[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load known words';
		} finally {
			loading = false;
		}
	});

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

	async function remove(word: string) {
		updatingWord = word;
		try {
			await api.deleteKnownWord(word);
			words = words.filter((w) => w.word !== word);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to delete';
		} finally {
			updatingWord = null;
		}
	}

	async function addWord() {
		const word = newWord.trim();
		if (!word || words.some((w) => w.word === word)) return;
		adding = true;
		try {
			const created = await api.upsertKnownWord(word, newFamiliarity) as KnownWord;
			words = [created, ...words];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add word';
		} finally {
			adding = false;
		}
	}
</script>

<svelte:head><title>Known Words - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- Known words are always global (see KnownWord's docstring, models.py) -
     no scope column needed here, unlike User Words. -->
<div class="bg-white rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 mb-2">Add a word</p>
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
		<span class="flex items-center gap-1.5 text-sm text-gray-700">
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
	<span class="text-sm text-gray-400">{filtered().length} of {words.length} words</span>
</div>

<!-- Shared flex row with the panel below (lg and up) - same mechanism as
     the analysis results page: the panel's own backdrop wrapper collapses
     to `display: contents` at `lg`, so its child joins this row as a
     sticky-positioned sibling instead of floating as a modal. -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 p-4">Loading...</p>
	{:else if words.length === 0}
		<p class="text-gray-500 p-4">No known words yet - add one above, or mark familiarity from any analysis.</p>
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
				{#each filtered() as w (w.id)}
					<tr class="cursor-pointer hover:bg-gray-50" onclick={(e) => handleRowClick(e, w.word)}>
						<td class="px-4 py-3 text-lg font-medium">{w.word}</td>
						<td class="px-4 py-3">
							<div class="flex gap-1">
								{#each [1, 2, 3, 4, 5] as score}
									<button
										onclick={() => setFamiliarity(w.word, score)}
										disabled={updatingWord === w.word}
										class="w-7 h-7 rounded text-xs font-medium disabled:opacity-50
										{w.familiarity === score ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
										title={familiarityLabel(score)}
									>
										{score}
									</button>
								{/each}
								<span class="text-xs px-2 py-1 rounded-full self-center {familiarityColor(w.familiarity)}">
									{familiarityLabel(w.familiarity)}
								</span>
							</div>
						</td>
						<td class="px-4 py-3">
							<button
								onclick={() => remove(w.word)}
								disabled={updatingWord === w.word}
								class="text-red-400 hover:text-red-600 text-sm disabled:opacity-50"
							>
								Delete
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
