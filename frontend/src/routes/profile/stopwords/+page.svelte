<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';

	interface StopwordRow {
		id: number;
		word: string;
		is_override: boolean;
		user_id: number | null;
	}

	let rows: StopwordRow[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let deleting: number | null = $state(null);

	let newWord = $state('');
	let newIsOverride = $state(false);
	let adding = $state(false);

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			rows = await api.listStopwords() as StopwordRow[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load stopwords';
		} finally {
			loading = false;
		}
	});

	const filtered = $derived(() => {
		const q = search.trim();
		return q ? rows.filter((r) => r.word.includes(q)) : rows;
	});

	async function remove(row: StopwordRow) {
		deleting = row.id;
		try {
			await api.deleteStopword(row.id);
			rows = rows.filter((r) => r.id !== row.id);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to delete';
		} finally {
			deleting = null;
		}
	}

	async function addWord() {
		const word = newWord.trim();
		if (!word) return;
		adding = true;
		try {
			const created = await api.createStopword(word, newIsOverride) as StopwordRow;
			rows = [created, ...rows];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add';
		} finally {
			adding = false;
		}
	}
</script>

<svelte:head><title>Stopwords - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- One unified stopword list - both the DAG and the tokenizer's repeated-
     sequence pass consult the same set now (see Stopword's docstring,
     models.py), so there's no more per-algorithm split to filter/badge by
     here. Note: this only shows rows actually in the database - the
     code-level default list (DEFAULT_STOPWORDS, service.py) that also
     applies isn't stored rows and has no API of its own, so it can't be
     listed or edited here. -->
<div class="bg-white rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 mb-2">Add a stopword</p>
	<div class="flex flex-wrap items-center gap-2">
		<input
			type="text"
			bind:value={newWord}
			placeholder="Word..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
			onkeydown={(e) => { if (e.key === 'Enter') addWord(); }}
		/>
		<label class="flex items-center gap-1.5 text-sm text-gray-600">
			<input type="checkbox" bind:checked={newIsOverride} class="rounded border-gray-300" />
			Override (exclude from the default list instead of adding to it)
		</label>
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
	<span class="text-sm text-gray-400">{filtered().length} of {rows.length} rows</span>
</div>

<div class="bg-white rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 p-4">Loading...</p>
	{:else if rows.length === 0}
		<p class="text-gray-500 p-4">No stopword rows yet - add one above.</p>
	{:else if filtered().length === 0}
		<p class="text-gray-500 p-4">No rows match.</p>
	{:else}
		<table class="w-full">
			<thead class="bg-gray-50 border-b border-gray-200">
				<tr>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Word</th>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Type</th>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100">
				{#each filtered() as r (r.id)}
					<tr class="hover:bg-gray-50">
						<td class="px-4 py-3 text-base">{r.word}</td>
						<td class="px-4 py-3">
							{#if r.user_id === null}
								<span class="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-500">system default</span>
							{:else if r.is_override}
								<span class="text-xs px-2 py-1 rounded-full bg-amber-100 text-amber-700">your override</span>
							{:else}
								<span class="text-xs px-2 py-1 rounded-full bg-emerald-100 text-emerald-700">your addition</span>
							{/if}
						</td>
						<td class="px-4 py-3">
							{#if r.user_id !== null}
								<button
									onclick={() => remove(r)}
									disabled={deleting === r.id}
									class="text-red-400 hover:text-red-600 text-sm disabled:opacity-50"
								>
									Delete
								</button>
							{:else}
								<span class="text-xs text-gray-300">-</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>
