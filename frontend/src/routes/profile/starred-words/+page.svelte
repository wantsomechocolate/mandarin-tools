<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import WordDetailPanel from '$lib/components/WordDetailPanel.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';

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
	let search = $state('');
	let saving: string | null = $state(null);

	let editingWord: string | null = $state(null);
	let noteDraft = $state('');

	let newWord = $state('');
	let newNote = $state('');
	let adding = $state(false);

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
		return q
			? rows.filter((r) => r.word.includes(q) || (r.note?.toLowerCase().includes(q.toLowerCase()) ?? false))
			: rows;
	});

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
		<div class="divide-y divide-gray-100">
			{#each filtered() as row (row.id)}
				<div class="flex items-start justify-between gap-3 px-4 py-3">
					<div class="flex-1 min-w-0">
						<button onclick={() => selectedWordForPanel = row.word} class="text-lg font-medium hover:text-blue-600" title="View details">
						{row.word}
					</button>
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
						{:else if row.note}
							<p class="text-sm text-gray-500 mt-0.5">{row.note}</p>
						{/if}
					</div>
					<div class="flex gap-2 shrink-0">
						{#if editingWord !== row.word}
							<button onclick={() => startEditing(row)} class="text-xs text-blue-600 hover:text-blue-800">
								{row.note ? 'Edit note' : '+ Note'}
							</button>
						{/if}
						<button
							onclick={() => remove(row.word)}
							disabled={saving === row.word}
							class="text-xs text-red-400 hover:text-red-600 disabled:opacity-50"
						>
							Unstar
						</button>
					</div>
				</div>
			{/each}
		</div>
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
				onGarbageMarked={() => {
					if (!selectedWordForPanel) return;
					rows = rows.filter((r) => r.word !== selectedWordForPanel);
				}}
			/>
		</div>
	</div>
{/if}
</div>
