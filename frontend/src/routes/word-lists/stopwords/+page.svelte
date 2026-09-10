<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';

	// Persisted filter preferences - see known-words/+page.svelte's own
	// FILTER_STORAGE_KEY comment for the full pattern and why search is
	// included here (unlike analyze/[id]'s). Search is the only filter this
	// page has - no sortable columns here.
	const FILTER_STORAGE_KEY = 'mandarin_tools_stopwords_filters';

	interface StoredFilters {
		search: string;
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

	interface StopwordRow {
		id: number;
		word: string;
		is_override: boolean;
		user_id: number | null;
	}

	let rows: StopwordRow[] = $state([]);
	// The code-level DEFAULT_STOPWORDS set (service.py) - see
	// listDefaultStopwords' docstring, api.ts. Loaded once alongside `rows`;
	// static for the life of the page (it's a code constant, not something
	// that changes at runtime).
	let defaultStopwords: string[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state(storedFilters.search ?? '');
	let deleting: number | null = $state(null);

	let newWord = $state('');
	let adding = $state(false);

	// Persist filter preferences on every change - see known-words'
	// identical effect for the reasoning.
	$effect(() => {
		if (!browser) return;
		try {
			const toStore: StoredFilters = { search };
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
			const [stopwordRows, defaults] = await Promise.all([
				api.listStopwords() as Promise<StopwordRow[]>,
				api.listDefaultStopwords() as Promise<string[]>,
			]);
			rows = stopwordRows;
			defaultStopwords = defaults;
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

	// A handful of the defaults are whitespace/invisible - shown as a
	// bracketed label instead of the raw (blank-looking) character, both in
	// the reference list below and in the add-form's own messages.
	function displayChar(w: string): string {
		switch (w) {
			case ' ': return '(space)';
			case '\t': return '(tab)';
			case '\n': return '(newline)';
			case '　': return '(full-width space)';
			default: return w;
		}
	}

	// True for a word that's already treated as a stopword without the user
	// doing anything: either a code-level default, or a DB-stored "system
	// default" row (user_id null) that isn't itself overridden. Mirrors
	// service.get_user_stopwords' own resolution (router.py), minus this
	// user's own rows - this check is specifically "would adding a plain
	// row here be redundant," which only the *default* layer can make true.
	function isBuiltInStopword(word: string): boolean {
		if (defaultStopwords.includes(word)) return true;
		return rows.some((r) => r.word === word && r.user_id === null && !r.is_override);
	}

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

	// create_stopword (router.py) errors on ANY existing row this user owns
	// for the word - plain addition or override, doesn't matter - so this
	// checks the same way, not just an exact (word, is_override) match. A
	// system-default row (user_id === null) doesn't count; the backend's own
	// duplicate check is scoped to the current user's rows too.
	const existingOwnStopword = $derived(
		rows.find((r) => r.word === newWord.trim() && r.user_id !== null) ?? null
	);

	// True exactly when the typed word is a default with no user row yet -
	// the one case where clicking the button should create an *override*,
	// not a plain addition. See addWord below and the template's button
	// label/warning, both keyed off this and existingOwnStopword.
	const newWordIsUncoveredDefault = $derived(
		!existingOwnStopword && newWord.trim() !== '' && isBuiltInStopword(newWord.trim())
	);

	// Replaces the old manual "Override" checkbox entirely - the checkbox
	// asked the user to already know whether a word was a default, which
	// they had no way to check (the default list was invisible - see the
	// explanation section below, added for the same reason). Now the button
	// itself decides: is_override is only ever true when the word is a
	// currently-uncovered default, which is the one situation where a plain
	// (non-override) row would be redundant and an override is actually
	// what "add this" should mean.
	async function addWord() {
		const word = newWord.trim();
		if (!word || existingOwnStopword) return;
		adding = true;
		try {
			const created = await api.createStopword(word, isBuiltInStopword(word)) as StopwordRow;
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
	<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- Added so this page explains itself rather than assuming the reader
     already knows what a stopword is or which ones apply by default - the
     latter used to be genuinely impossible to find out, since
     DEFAULT_STOPWORDS (service.py) was a code constant with no API of its
     own until listDefaultStopwords/list_default_stopwords (api.ts,
     router.py) were added specifically for this. -->
<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4 mb-4">
	<h2 class="text-sm font-semibold text-gray-700 dark:text-slate-300 mb-1.5">What are stopwords?</h2>
	<p class="text-sm text-gray-600 dark:text-slate-400 mb-2">
		Characters the segmenter treats as pure boundaries, not real words - mostly punctuation and
		whitespace. A word can never start with or extend through a stopword, and a stopword never
		shows up on its own as an "unrecognized sequence" either.
	</p>
	<p class="text-sm text-gray-600 dark:text-slate-400 mb-3">
		They're consulted in two places, both the same list: the DAG segmenter's own word-boundary
		scan, and the tokenizer's repeated-sequence pass (the one that flags runs of unrecognized
		characters worth reviewing) - both simply skip over every stopword the same way.
	</p>
	<p class="text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
		Default stopwords - always on, built into the app, not something you can edit directly:
	</p>
	<div class="flex flex-wrap gap-1.5">
		{#each defaultStopwords as w}
			<span class="text-xs font-mono px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300">{displayChar(w)}</span>
		{/each}
	</div>
	<p class="text-xs text-gray-400 dark:text-slate-500 mt-2">
		Don't want one of these treated as a stopword? Type it below - since it's already covered by
		default, the button will offer to exclude it instead of adding a redundant row.
	</p>
</div>

<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 dark:text-slate-400 mb-2">Add a stopword</p>
	<div class="flex flex-wrap items-center gap-2">
		<input
			type="text"
			bind:value={newWord}
			placeholder="Word..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
			onkeydown={(e) => { if (e.key === 'Enter') addWord(); }}
		/>
		<button
			onclick={addWord}
			disabled={!newWord.trim() || adding || !!existingOwnStopword}
			class="text-sm px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
		>
			{adding ? 'Adding...' : existingOwnStopword ? 'Already added' : newWordIsUncoveredDefault ? 'Exclude it' : 'Add'}
		</button>
	</div>
	{#if existingOwnStopword}
		<p class="text-xs text-amber-600 mt-2">
			{#if existingOwnStopword.is_override}
				You've already excluded "{displayChar(existingOwnStopword.word)}" from being treated as a stopword.
			{:else}
				You've already added "{displayChar(existingOwnStopword.word)}" as a stopword.
			{/if}
			<button
				onclick={() => remove(existingOwnStopword)}
				disabled={deleting === existingOwnStopword.id}
				class="underline hover:text-amber-800 disabled:opacity-50"
			>
				{existingOwnStopword.is_override ? 'Remove the exclusion' : 'Remove it'}
			</button>
		</p>
	{:else if newWordIsUncoveredDefault}
		<p class="text-xs text-blue-600 dark:text-blue-400 mt-2">
			"{displayChar(newWord.trim())}" is already a stopword by default - clicking "Exclude it" will stop it
			from being treated as one, instead of adding a redundant row.
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
	<span class="text-sm text-gray-400 dark:text-slate-500">{filtered().length} of {rows.length} rows</span>
</div>

<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 dark:text-slate-400 p-4">Loading...</p>
	{:else if rows.length === 0}
		<p class="text-gray-500 dark:text-slate-400 p-4">No stopword rows yet - add one above.</p>
	{:else if filtered().length === 0}
		<p class="text-gray-500 dark:text-slate-400 p-4">No rows match.</p>
	{:else}
		<table class="w-full">
			<thead class="bg-gray-50 dark:bg-slate-950 border-b border-gray-200 dark:border-slate-800">
				<tr>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700 dark:text-slate-300">Word</th>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700 dark:text-slate-300">Type</th>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700 dark:text-slate-300">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100 dark:divide-slate-800">
				{#each filtered() as r (r.id)}
					<tr class="hover:bg-gray-50 dark:hover:bg-slate-800">
						<td class="px-4 py-3 text-base">{displayChar(r.word)}</td>
						<td class="px-4 py-3">
							{#if r.user_id === null}
								<span class="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-500 dark:bg-slate-500/15 dark:text-slate-400">system default</span>
							{:else if r.is_override}
								<span class="text-xs px-2 py-1 rounded-full bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">your override</span>
							{:else}
								<span class="text-xs px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">your addition</span>
							{/if}
						</td>
						<td class="px-4 py-3">
							{#if r.user_id !== null}
								<button
									onclick={() => remove(r)}
									disabled={deleting === r.id}
									class="text-red-400 hover:text-red-600 dark:hover:text-red-400 text-sm disabled:opacity-50"
								>
									Delete
								</button>
							{:else}
								<span class="text-xs text-gray-300 dark:text-slate-600">-</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>
