<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import type { ScopeContext } from '$lib/api';
	import { goto } from '$app/navigation';

	interface UserWordRow {
		id: number;
		word: string;
		pronunciation: string | null;
		meaning: string | null;
		notes: string | null;
		affects_dag: boolean | null;
		scope_analysis_id: number | null;
		scope_input_text_id: number | null;
		input_text_title: string | null;
	}

	let rows: UserWordRow[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let scopeFilter: 'all' | 'global' | 'text' | 'analysis' = $state('all');

	// Per-row inline editing - same pattern as the analysis-results panel's
	// "Your entries" list, just without a single "currently selected word"
	// context (every row here can be a different word).
	let editingIds: Set<number> = $state(new Set());
	let drafts: Record<number, { pronunciation: string; meaning: string; notes: string; affectsDag: boolean | null }> = $state({});
	let savingId: number | null = $state(null);

	let newWord = $state('');
	let adding = $state(false);

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			rows = await api.listAllUserWords() as UserWordRow[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load user words';
		} finally {
			loading = false;
		}
	});

	function scopeOf(row: UserWordRow): 'global' | 'text' | 'analysis' {
		if (row.scope_analysis_id != null) return 'analysis';
		if (row.scope_input_text_id != null) return 'text';
		return 'global';
	}

	function scopeLabel(row: UserWordRow): string {
		if (row.scope_analysis_id != null) {
			return row.input_text_title ? `Analysis of "${row.input_text_title}"` : `Analysis #${row.scope_analysis_id}`;
		}
		if (row.scope_input_text_id != null) {
			return `Text: ${row.input_text_title ?? 'Untitled'}`;
		}
		return 'Global';
	}

	function scopeLink(row: UserWordRow): string | null {
		if (row.scope_analysis_id != null) return `/analyze/${row.scope_analysis_id}`;
		if (row.scope_input_text_id != null) return `/input-texts/${row.scope_input_text_id}`;
		return null;
	}

	// Only what _resolve_scope_columns (router.py) actually reads for each
	// scope - analysis_id for 'analysis', input_text_id for 'text', neither
	// for 'global' (see that function's docstring for confirmation this is
	// exhaustive).
	function scopeContextForRow(row: UserWordRow): ScopeContext {
		if (row.scope_analysis_id != null) return { scope: 'analysis', analysisId: row.scope_analysis_id };
		if (row.scope_input_text_id != null) return { scope: 'text', inputTextId: row.scope_input_text_id };
		return { scope: 'global' };
	}

	const filtered = $derived(() => {
		const q = search.trim().toLowerCase();
		return rows.filter((r) => {
			if (scopeFilter !== 'all' && scopeOf(r) !== scopeFilter) return false;
			if (!q) return true;
			return r.word.includes(search.trim())
				|| (r.pronunciation?.toLowerCase().includes(q) ?? false)
				|| (r.meaning?.toLowerCase().includes(q) ?? false)
				|| (r.notes?.toLowerCase().includes(q) ?? false);
		});
	});

	function startEditing(row: UserWordRow) {
		drafts = { ...drafts, [row.id]: {
			pronunciation: row.pronunciation ?? '',
			meaning: row.meaning ?? '',
			notes: row.notes ?? '',
			affectsDag: row.affects_dag,
		}};
		editingIds = new Set([...editingIds, row.id]);
	}

	function cancelEditing(id: number) {
		const next = new Set(editingIds);
		next.delete(id);
		editingIds = next;
	}

	async function saveRow(row: UserWordRow) {
		savingId = row.id;
		try {
			const draft = drafts[row.id];
			const isAnalysisScoped = row.scope_analysis_id != null;
			const fields: { pronunciation: string | null; meaning: string | null; notes: string | null; affects_dag?: boolean | null } = {
				pronunciation: draft.pronunciation || null,
				meaning: draft.meaning || null,
				notes: draft.notes || null,
			};
			// affects_dag is never sent for an analysis-scoped row - it has no
			// observable effect there (see UserWord's docstring, models.py),
			// and the toggle isn't shown for one.
			if (!isAnalysisScoped) fields.affects_dag = draft.affectsDag;
			const updated = await api.upsertUserWordDetail(row.word, fields, scopeContextForRow(row)) as UserWordRow;
			rows = rows.map((r) => r.id === row.id ? { ...updated, input_text_title: row.input_text_title } : r);
			cancelEditing(row.id);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to save';
		} finally {
			savingId = null;
		}
	}

	async function remove(row: UserWordRow) {
		savingId = row.id;
		try {
			await api.deleteUserWord(row.word, row.scope_analysis_id, row.scope_input_text_id);
			rows = rows.filter((r) => r.id !== row.id);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to delete';
		} finally {
			savingId = null;
		}
	}

	// Always global - a new entry from this page has no "current text/
	// analysis" to scope to. Text/analysis-scoped entries are added from
	// within that specific analysis's word-detail panel instead.
	async function addWord() {
		const word = newWord.trim();
		if (!word) return;
		adding = true;
		try {
			const created = await api.upsertUserWordDetail(word, { affects_dag: true }, { scope: 'global' }) as UserWordRow;
			rows = [{ ...created, input_text_title: null }, ...rows];
			newWord = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add word';
		} finally {
			adding = false;
		}
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
     WordDetail.user_words' docstring (schemas.py). This page shows every
     row across every scope, unresolved - not the one-per-word resolution
     build_user_overlay uses for segmentation. -->
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
	<div class="flex items-center gap-2">
		<input
			type="search"
			bind:value={search}
			placeholder="Search word, pronunciation, meaning, notes..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-64"
		/>
		<select bind:value={scopeFilter} class="border border-gray-300 rounded px-2 py-1 text-sm">
			<option value="all">All scopes</option>
			<option value="global">Global</option>
			<option value="text">Text-scoped</option>
			<option value="analysis">Analysis-scoped</option>
		</select>
	</div>
	<span class="text-sm text-gray-400">{filtered().length} of {rows.length} entries</span>
</div>

<div class="bg-white rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 p-4">Loading...</p>
	{:else if rows.length === 0}
		<p class="text-gray-500 p-4">No user words yet - add one above, or from any analysis's word panel.</p>
	{:else if filtered().length === 0}
		<p class="text-gray-500 p-4">No entries match.</p>
	{:else}
		<div class="divide-y divide-gray-100">
			{#each filtered() as row (row.id)}
				{@const editing = editingIds.has(row.id)}
				{@const link = scopeLink(row)}
				<div class="p-4">
					<div class="flex items-start justify-between gap-3 mb-1">
						<div class="flex items-center gap-2 flex-wrap">
							<span class="text-lg font-medium">{row.word}</span>
							{#if link}
								<a href={link} class="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 hover:bg-indigo-200">
									{scopeLabel(row)}
								</a>
							{:else}
								<span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">Global</span>
							{/if}
							{#if scopeOf(row) !== 'analysis' && row.affects_dag === false}
								<span class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">Excluded from segmentation</span>
							{/if}
						</div>
						<div class="flex gap-2 shrink-0">
							{#if !editing}
								<button onclick={() => startEditing(row)} class="text-xs text-blue-600 hover:text-blue-800">Edit</button>
							{/if}
							<button
								onclick={() => remove(row)}
								disabled={savingId === row.id}
								class="text-xs text-red-400 hover:text-red-600 disabled:opacity-50"
							>
								Delete
							</button>
						</div>
					</div>

					{#if editing}
						<div class="space-y-2 mt-2">
							<div class="grid sm:grid-cols-2 gap-2">
								<div>
									<label for="pron-{row.id}" class="text-xs text-gray-500">Pronunciation</label>
									<input
										id="pron-{row.id}"
										type="text"
										bind:value={drafts[row.id].pronunciation}
										class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
									/>
								</div>
								<div>
									<label for="meaning-{row.id}" class="text-xs text-gray-500">Meaning</label>
									<input
										id="meaning-{row.id}"
										type="text"
										bind:value={drafts[row.id].meaning}
										class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
									/>
								</div>
							</div>
							<div>
								<label for="notes-{row.id}" class="text-xs text-gray-500">Notes</label>
								<textarea
									id="notes-{row.id}"
									bind:value={drafts[row.id].notes}
									rows="2"
									class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
								></textarea>
							</div>
							{#if scopeOf(row) !== 'analysis'}
								<!-- Tri-state, not a checkbox - NULL ("no preference") is a
								     real, distinct value from false ("excluded"), not just
								     "unchecked". A plain checkbox can't represent that third
								     state, and would silently coerce an untouched NULL to
								     false on save - see affects_dag's docstring (models.py). -->
								<div class="text-xs text-gray-500">
									<span class="block mb-1">Segmentation weight</span>
									<label class="flex items-center gap-1.5 mb-0.5">
										<input
											type="radio"
											name="affects-dag-{row.id}"
											checked={drafts[row.id].affectsDag === true}
											onchange={() => drafts[row.id].affectsDag = true}
										/>
										Affects segmentation
									</label>
									<label class="flex items-center gap-1.5 mb-0.5">
										<input
											type="radio"
											name="affects-dag-{row.id}"
											checked={drafts[row.id].affectsDag === false}
											onchange={() => drafts[row.id].affectsDag = false}
										/>
										Excluded from segmentation
									</label>
									<label class="flex items-center gap-1.5">
										<input
											type="radio"
											name="affects-dag-{row.id}"
											checked={drafts[row.id].affectsDag === null}
											onchange={() => drafts[row.id].affectsDag = null}
										/>
										No preference (inherit from broader scope)
									</label>
								</div>
							{/if}
							<div class="flex gap-2 pt-1">
								<button
									onclick={() => saveRow(row)}
									disabled={savingId === row.id}
									class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
								>
									{savingId === row.id ? 'Saving...' : 'Save'}
								</button>
								<button
									onclick={() => cancelEditing(row.id)}
									disabled={savingId === row.id}
									class="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700"
								>
									Cancel
								</button>
							</div>
						</div>
					{:else}
						<div class="space-y-0.5">
							{#if row.pronunciation}<p class="text-sm text-blue-600">{row.pronunciation}</p>{/if}
							{#if row.meaning}<p class="text-sm text-gray-700">{row.meaning}</p>{/if}
							{#if row.notes}<p class="text-xs text-gray-500 italic">{row.notes}</p>{/if}
							{#if !row.pronunciation && !row.meaning && !row.notes}<p class="text-sm text-gray-400">No details added.</p>{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
