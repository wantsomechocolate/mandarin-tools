<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';

	interface GarbageWordRow {
		id: number;
		word: string;
		is_override: boolean;
		user_id: number | null;
	}

	let raw: GarbageWordRow[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let updating: string | null = $state(null);

	let newWord = $state('');
	let adding = $state(false);

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
		return q ? resolvedGarbage().filter((g) => g.word.includes(q)) : resolvedGarbage();
	});

	async function unmark(word: string) {
		updating = word;
		try {
			await api.unmarkGarbageWord(word);
			raw = raw.filter((g) => !(g.word === word && !g.is_override));
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

	async function addWord() {
		const word = newWord.trim();
		if (!word) return;
		adding = true;
		try {
			const created = await api.createGarbageWord(word, false) as GarbageWordRow;
			raw = [created, ...raw];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add';
		} finally {
			adding = false;
		}
	}
</script>

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
		placeholder="Search words..."
		class="border border-gray-300 rounded px-2 py-1 text-sm w-48"
	/>
	<span class="text-sm text-gray-400">{filteredGarbage().length} of {resolvedGarbage().length} words</span>
</div>

<div class="bg-white rounded-lg shadow-sm overflow-hidden mb-6">
	{#if loading}
		<p class="text-gray-500 p-4">Loading...</p>
	{:else if resolvedGarbage().length === 0}
		<p class="text-gray-500 p-4">No garbage words currently marked.</p>
	{:else if filteredGarbage().length === 0}
		<p class="text-gray-500 p-4">No words match.</p>
	{:else}
		<div class="divide-y divide-gray-100">
			{#each filteredGarbage() as g (g.word)}
				<div class="flex items-center justify-between px-4 py-2.5">
					<div class="flex items-center gap-2">
						<span class="text-base">{g.word}</span>
						{#if g.systemDefault}
							<span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">system default</span>
						{/if}
					</div>
					<button
						onclick={() => unmark(g.word)}
						disabled={updating === g.word}
						class="text-red-400 hover:text-red-600 text-sm disabled:opacity-50"
					>
						Un-mark
					</button>
				</div>
			{/each}
		</div>
	{/if}
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
