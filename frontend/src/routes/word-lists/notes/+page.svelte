<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import WordDetailModal from '$lib/components/WordDetailModal.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';
	import { saveOpenWordPanel, loadOpenWordPanel } from '$lib/panelWordPersistence';
	import { trackScrollPosition, restoreScrollPosition } from '$lib/scrollPersistence';

	// Global list page - see the matching comment in known-words/+page.svelte.
	const panelContext: WordDetailContext = { type: 'global' };
	// See panelWordPersistence.ts's docstring - recovers which word's panel
	// was open across a mobile browser's involuntary page reload.
	let selectedWordForPanel: string | null = $state(loadOpenWordPanel());
	$effect(() => {
		saveOpenWordPanel(selectedWordForPanel);
	});

	// Persisted filter preferences - see known-words/+page.svelte's own
	// FILTER_STORAGE_KEY comment for the full pattern and why search is
	// included here (unlike analyze/[id]'s).
	const FILTER_STORAGE_KEY = 'mandarin_tools_notes_filters';

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

	interface WordNoteRow {
		id: number;
		word: string;
		note: string;
	}

	let rows: WordNoteRow[] = $state([]);
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
	let saving: string | null = $state(null);

	// "Add a note" form state, at the top of the page - see addNote below
	// for why this exists now (it didn't originally).
	let newWord = $state('');
	let newNote = $state('');
	let adding = $state(false);

	// Which row's note is currently being edited inline (clicking the note
	// side of a row, not the word side - see handleNoteClick).
	let editingWord: string | null = $state(null);
	let noteDraft = $state('');

	// Both columns sortable - Word by plain codepoint (same reasoning as
	// every other word list's identical toggleSort), Note by plain string
	// comparison (notes are free text, not necessarily Chinese, so no
	// codepoint-vs-pinyin concern applies the way it does for Word).
	type SortColumn = 'word' | 'note' | null;
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
			rows = await api.listWordNotes() as WordNoteRow[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load notes';
		} finally {
			loading = false;
		}
	});

	const filtered = $derived(() => {
		const q = search.trim();
		let list = q
			? rows.filter((r) => r.word.includes(q) || r.note.toLowerCase().includes(q.toLowerCase()))
			: rows;
		if (sortColumn) {
			list = [...list].sort((a, b) => {
				const cmp = a[sortColumn!] < b[sortColumn!] ? -1 : a[sortColumn!] > b[sortColumn!] ? 1 : 0;
				return sortDirection === 'desc' ? -cmp : cmp;
			});
		}
		return list;
	});

	// Word side opens the info pane - same click-passthrough pattern as
	// every other list page.
	function handleWordClick(event: MouseEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		selectedWordForPanel = word;
	}

	// Note side starts inline editing instead - the same guard excludes
	// clicks on the Save/Cancel/Delete buttons and the textarea once
	// editing is already underway, so it doesn't re-trigger itself.
	function handleNoteClick(event: MouseEvent, row: WordNoteRow) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		editingWord = row.word;
		noteDraft = row.note;
	}

	// Empty/whitespace-only text deletes the note server-side (see
	// upsert_word_note's docstring, router.py) - a word with no note has no
	// reason to appear on this page at all, so it drops out of the list
	// entirely, same "cleared score removes the row" pattern Known Words'
	// own setFamiliarity already uses.
	async function saveNote(word: string) {
		const trimmed = noteDraft.trim();
		saving = word;
		try {
			await api.upsertWordNote(word, trimmed);
			if (trimmed) {
				rows = rows.map((r) => r.word === word ? { ...r, note: trimmed } : r);
			} else {
				rows = rows.filter((r) => r.word !== word);
			}
			editingWord = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to save note';
		} finally {
			saving = null;
		}
	}

	async function removeNote(word: string) {
		saving = word;
		try {
			await api.deleteWordNote(word);
			rows = rows.filter((r) => r.word !== word);
			editingWord = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove note';
		} finally {
			saving = null;
		}
	}

	// Reactive lookup so the form can warn before the word is even submitted,
	// not just gate on click - existingNoteForNewWord is null both when
	// newWord is blank and when it doesn't match any row, so the template
	// can use it directly as the "show a warning" condition.
	const existingNoteForNewWord = $derived(
		rows.find((r) => r.word === newWord.trim()) ?? null
	);

	// Added so this page matches the other five profile tabs, which all let
	// you add a word from the top of the page without first going through an
	// existing text - a note previously could only ever start from a word's
	// info pane (opened via a row click elsewhere). Reuses upsertWordNote,
	// the same endpoint saveNote above already calls - a note for a
	// not-yet-listed word is exactly what an upsert of a fresh word is.
	//
	// Re-adding a word that already has a note replaces it in place (same
	// upsert semantics as saveNote's own edit path) rather than erroring as
	// a duplicate - but doing that *silently* from this form is exactly the
	// mistake this used to make: unlike the inline edit path (where the old
	// note is right there on screen as you overwrite it), typing a word here
	// gives no indication a note already exists until it's already gone.
	// confirm() with the existing note's text shown gates that one
	// destructive case - same pattern this app already uses for its one
	// other "can't undo this" action (deleting an input text, +page.svelte).
	async function addNote() {
		const word = newWord.trim();
		const note = newNote.trim();
		if (!word || !note) return;

		const existing = rows.find((r) => r.word === word);
		if (existing) {
			const proceed = confirm(
				`"${word}" already has a note:\n\n"${existing.note}"\n\nReplace it with the new note?`
			);
			if (!proceed) return;
		}

		adding = true;
		try {
			const saved = await api.upsertWordNote(word, note) as WordNoteRow;
			rows = [saved, ...rows.filter((r) => r.word !== word)];
			newWord = '';
			newNote = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add note';
		} finally {
			adding = false;
		}
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

<svelte:head><title>Notes - Mandarin Tools</title></svelte:head>

{#if error}
	<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<!-- Mirrors the other profile tabs' "add at the top" card (Starred/Known/
     User/Garbage/Stopwords) - a note needs actual text to be worth saving
     (an empty note is a no-op server-side, see upsertWordNote's docstring,
     api.ts), so this form takes both fields at once rather than just a
     bare word like those other pages' forms do. -->
<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4 mb-4">
	<p class="text-sm font-medium text-gray-600 dark:text-slate-400 mb-2">Add a note</p>
	<div class="flex flex-wrap items-start gap-2">
		<input
			type="text"
			bind:value={newWord}
			placeholder="Word..."
			class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
		/>
		<textarea
			bind:value={newNote}
			placeholder="Note..."
			rows="1"
			class="border border-gray-300 rounded px-2 py-1 text-sm flex-1 min-w-[10rem] resize-none"
		></textarea>
		<button
			onclick={addNote}
			disabled={!newWord.trim() || !newNote.trim() || adding}
			class="text-sm px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
		>
			{adding ? 'Adding...' : existingNoteForNewWord ? 'Replace note' : 'Add'}
		</button>
	</div>
	<!-- Warns before submission, not just at the confirm() gate in addNote -
	     seeing this while still typing is what actually prevents the
	     "silent overwrite" surprise; the confirm() dialog is the backstop
	     for anyone who doesn't notice this. -->
	{#if existingNoteForNewWord}
		<p class="text-xs text-amber-600 mt-2">
			"{existingNoteForNewWord.word}" already has a note: "{existingNoteForNewWord.note}" — adding here will replace it.
		</p>
	{/if}
</div>

<div class="flex items-center justify-between mb-3 gap-3 flex-wrap">
	<input
		type="search"
		bind:value={search}
		placeholder="Search words or notes..."
		class="border border-gray-300 rounded px-2 py-1 text-sm w-56"
	/>
	<span class="text-sm text-gray-400 dark:text-slate-500">{filtered().length} of {rows.length} words</span>
</div>

<!-- Shared flex row with the panel below (lg and up) - same mechanism as
     the analysis results page: the panel's own backdrop wrapper collapses
     to `display: contents` at `lg`, so its child joins this row as a
     sticky-positioned sibling instead of floating as a modal. -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white dark:bg-slate-900 rounded-lg shadow-sm overflow-hidden">
	{#if loading}
		<p class="text-gray-500 dark:text-slate-400 p-4">Loading...</p>
	{:else if rows.length === 0}
		<p class="text-gray-500 dark:text-slate-400 p-4">No notes yet - add one from any word's info pane.</p>
	{:else if filtered().length === 0}
		<p class="text-gray-500 dark:text-slate-400 p-4">No words match.</p>
	{:else}
		<table class="w-full">
			<thead class="bg-gray-50 dark:bg-slate-950 border-b border-gray-200 dark:border-slate-800">
				<tr>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700 dark:text-slate-300">
						<button onclick={() => toggleSort('word')} class="inline-flex items-center gap-1 hover:text-blue-600 dark:hover:text-blue-400 {sortColumn === 'word' ? 'text-blue-600 dark:text-blue-400' : ''}">
							Word {#if sortColumn === 'word'}{@render iconChevron(sortDirection === 'asc')}{/if}
						</button>
					</th>
					<th class="text-left px-4 py-3 text-sm font-medium text-gray-700 dark:text-slate-300">
						<button onclick={() => toggleSort('note')} class="inline-flex items-center gap-1 hover:text-blue-600 dark:hover:text-blue-400 {sortColumn === 'note' ? 'text-blue-600 dark:text-blue-400' : ''}">
							Note {#if sortColumn === 'note'}{@render iconChevron(sortDirection === 'asc')}{/if}
						</button>
					</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100 dark:divide-slate-800">
				{#each filtered() as row (row.id)}
					<tr class="hover:bg-gray-50 dark:hover:bg-slate-800">
						<td class="px-4 py-3 align-top cursor-pointer" onclick={(e) => handleWordClick(e, row.word)}>
							<p class="text-lg font-medium">{row.word}</p>
						</td>
						<td class="px-4 py-3 align-top cursor-pointer" onclick={(e) => handleNoteClick(e, row)}>
							{#if editingWord === row.word}
								<div class="flex flex-col gap-1.5">
									<textarea
										bind:value={noteDraft}
										rows="2"
										class="border border-gray-300 rounded px-2 py-1 text-sm resize-none"
									></textarea>
									<div class="flex items-center gap-2">
										<button onclick={() => saveNote(row.word)} disabled={saving === row.word} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
											{saving === row.word ? 'Saving...' : 'Save'}
										</button>
										<button onclick={() => editingWord = null} disabled={saving === row.word} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
										<button onclick={() => removeNote(row.word)} disabled={saving === row.word} class="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-400 ml-auto">Delete</button>
									</div>
								</div>
							{:else}
								<p class="text-sm text-gray-700 dark:text-slate-300 whitespace-pre-wrap break-words">{row.note}</p>
							{/if}
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
		onNoteChanged={(note) => {
			if (!selectedWordForPanel) return;
			const word = selectedWordForPanel;
			if (note) {
				rows = rows.map((r) => r.word === word ? { ...r, note } : r);
			} else {
				rows = rows.filter((r) => r.word !== word);
			}
		}}
		onGarbageMarked={() => {
			if (!selectedWordForPanel) return;
			rows = rows.filter((r) => r.word !== selectedWordForPanel);
		}}
	/>
</div>
