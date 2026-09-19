<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import AccountMenu from '$lib/components/AccountMenu.svelte';
	import ReadingView from '$lib/components/ReadingView.svelte';
	import { loadRepeatedSequencePreferences } from '$lib/repeatedSequencePreferences';
	import { loadReadingViewOn, saveReadingViewOn } from '$lib/readingViewPersistence';

	interface AnalysisSummary {
		id: number;
		created_at: string;
		total_words: number;
		unique_words: number;
		min_token_length: number;
		max_token_length: number;
		min_token_count: number;
		min_familiarity_filter: number;
		max_familiarity_filter: number;
	}

	interface InputTextDetail {
		id: number;
		title: string | null;
		note: string | null;
		body: string;
		created_at: string;
		updated_at: string;
		analyses: AnalysisSummary[];
	}

	let inputText: InputTextDetail | null = $state(null);
	let loading = $state(true);
	let error = $state('');
	let reanalyzing = $state(false);

	// Reading view (segmented, colorable, annotatable) is opt-in, mirroring
	// analyze/[id]'s own "Reading view" toggle and reusing the same
	// per-analysis persistence - default is the plain body paragraph below
	// (real text nodes: selectable/copyable, no per-word buttons), not
	// ReadingView, since that's the closer match to this app's original
	// plain "Source text" view. Seeded once inputText loads (onMount, below)
	// rather than a reactive reseed effect - unlike analyze/[id], this page
	// doesn't need to handle the same mounted instance being reused for a
	// different id.
	let readingViewOn = $state(false);
	$effect(() => {
		if (inputText && inputText.analyses.length > 0) {
			saveReadingViewOn(inputText.analyses[0].id, readingViewOn);
		}
	});

	// Title editing - inline pencil-click-to-edit, same shape as the note
	// editing below (editing flag + draft + Save/Cancel), just single-line.
	let editingTitle = $state(false);
	let titleDraft = $state('');
	let savingTitle = $state(false);

	// Note editing - mirrors WordDetailPanel's own note section
	// (editingNote/noteDraft/savingNote, Save/Cancel/+ Add note) for a
	// consistent editing pattern across the app.
	let editingNote = $state(false);
	let noteDraft = $state('');
	let savingNote = $state(false);

	const id = $derived(parseInt($page.params.id ?? '0'));

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			inputText = await api.getInputText(id) as InputTextDetail;
			if (inputText.analyses.length > 0) {
				readingViewOn = loadReadingViewOn(inputText.analyses[0].id);
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load text';
		} finally {
			loading = false;
		}
	});

	async function handleReanalyze() {
		reanalyzing = true;
		error = '';
		try {
			// Account-level setting (Account page's "Advanced" card) - see
			// repeatedSequencePreferences.ts.
			const thresholds = await loadRepeatedSequencePreferences();
			const result = await api.reanalyzeInputText(id, thresholds) as any;
			goto(`/analyze/${result.analysis_id}`);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to re-analyze';
			reanalyzing = false;
		}
	}

	// Deletes just this one analysis run, not the input text - same
	// confirm()-then-delete-then-drop-locally shape as the home page's own
	// handleDelete (deleteInputText).
	let deletingAnalysisId: number | null = $state(null);
	async function handleDeleteAnalysis(analysisId: number) {
		if (!inputText) return;
		if (!confirm('Delete this analysis?')) return;
		deletingAnalysisId = analysisId;
		try {
			await api.deleteAnalysis(analysisId);
			inputText.analyses = inputText.analyses.filter((a) => a.id !== analysisId);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to delete analysis';
		} finally {
			deletingAnalysisId = null;
		}
	}

	async function saveTitle() {
		if (!inputText) return;
		savingTitle = true;
		try {
			const trimmed = titleDraft.trim();
			await api.updateInputText(id, { title: trimmed || null });
			inputText.title = trimmed || null;
			editingTitle = false;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to rename';
		} finally {
			savingTitle = false;
		}
	}

	async function saveNote() {
		if (!inputText) return;
		savingNote = true;
		try {
			const trimmed = noteDraft.trim();
			await api.updateInputText(id, { note: trimmed || null });
			inputText.note = trimmed || null;
			editingNote = false;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to save note';
		} finally {
			savingNote = false;
		}
	}

	async function removeNote() {
		if (!inputText) return;
		savingNote = true;
		try {
			await api.updateInputText(id, { note: null });
			inputText.note = null;
			editingNote = false;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove note';
		} finally {
			savingNote = false;
		}
	}
</script>

{#snippet iconPencil()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M13.5 3.5a1.5 1.5 0 0 1 2.12 2.12L6.5 14.75l-3 .75.75-3 9.25-9z" />
	</svg>
{/snippet}

{#snippet iconHome()}
	<svg class="w-8 h-8 block" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 9.5L10 4l6.5 5.5" />
		<path d="M5 8.5v7.75a0.25 0.25 0 0 0 0.25 0.25h9.5a0.25 0.25 0 0 0 0.25-0.25v-7.75" />
	</svg>
{/snippet}

<!-- Bar-chart glyph for "results" links - the header's "See latest results"
     next to the title, and each row's own "View results" in the Analyses
     list below. Same glyph, two sizes (the header one sits at 8x8 like the
     home icon beside it; each list row is smaller at 7x7), so this takes
     its size as a parameter rather than being duplicated. The counterpart
     to analyze/[id]'s own book icon (View source text): book = the text,
     chart = what came out of analyzing it, rather than an app-specific
     "segmented text" glyph nobody's seen before. -->
{#snippet iconBarChart(sizeClass: string)}
	<svg class="{sizeClass} block" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 16.5h13" />
		<path d="M6 16.5V11" />
		<path d="M10 16.5V6.5" />
		<path d="M14 16.5V9" />
	</svg>
{/snippet}

<!-- Same glyph as the home page's own iconTrashCan (input text delete) -
     kept as its own copy rather than a shared import, matching this app's
     existing per-file icon-snippet convention. Takes a size param like
     iconBarChart above, for the same reason: one glyph, used at this
     page's one size. -->
{#snippet iconTrashCan(sizeClass: string)}
	<svg class={sizeClass} viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M4.5 6h11" />
		<path d="M8 6V4.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1V6" />
		<path d="M6 6l.7 9.5a1 1 0 0 0 1 .93h4.6a1 1 0 0 0 1-.93L14 6" />
		<path d="M8.5 9v4.5" />
		<path d="M11.5 9v4.5" />
	</svg>
{/snippet}

<div class="min-h-screen bg-gray-50 dark:bg-slate-950">
	<!-- Same dynamic-title risk as analyze/[id] (a Chinese title has no
	     spaces to wrap on) - min-w-0 + truncate + title= protects it. -->
	<nav class="bg-white dark:bg-slate-900 shadow-sm px-6 py-4 flex items-center justify-between gap-4">
		<div class="flex items-center gap-4 min-w-0">
			<a href="/" class="text-gray-600 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 shrink-0" aria-label="Home" title="Home">
				{@render iconHome()}
			</a>
			<h1 class="text-xl font-bold text-gray-800 dark:text-slate-200 min-w-0 truncate" title={inputText?.title ?? 'Untitled'}>
				{inputText?.title ?? 'Untitled'}
			</h1>
			{#if inputText && inputText.analyses.length > 0}
				<a
					href="/analyze/{inputText.analyses[0].id}"
					class="text-gray-600 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 shrink-0"
					aria-label="View latest results"
					title="View latest results"
				>
					{@render iconBarChart('w-8 h-8')}
				</a>
			{/if}
		</div>
		<AccountMenu />
	</nav>

	<main class="max-w-5xl lg:max-w-6xl 2xl:max-w-7xl mx-auto px-6 py-8">
		{#if error}
			<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		{#if loading}
			<p class="text-gray-500 dark:text-slate-400">Loading...</p>
		{:else if inputText}
			<!-- Title & note - editable any time, separate card from the
			     read-only Source text below it since these two are edited
			     independently (title/note here, body never edited after
			     creation - re-analyzing or creating a new text is the path
			     for a changed body). -->
			<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6 mb-6">
				<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">Title</p>
				{#if editingTitle}
					<div class="flex items-center gap-2 mb-4">
						<input
							type="text"
							bind:value={titleDraft}
							placeholder="Untitled"
							class="flex-1 min-w-0 border border-gray-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 rounded px-2 py-1 text-sm"
							onkeydown={(e) => { if (e.key === 'Enter') saveTitle(); if (e.key === 'Escape') editingTitle = false; }}
						/>
						<button onclick={saveTitle} disabled={savingTitle} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
							{savingTitle ? 'Saving...' : 'Save'}
						</button>
						<button onclick={() => editingTitle = false} disabled={savingTitle} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
					</div>
				{:else}
					<div class="flex items-center gap-2 mb-4">
						<p class="text-sm text-gray-800 dark:text-slate-200">{inputText.title ?? 'Untitled'}</p>
						<button
							onclick={() => { editingTitle = true; titleDraft = inputText?.title ?? ''; }}
							class="text-gray-400 dark:text-slate-500 hover:text-blue-600 dark:hover:text-blue-400"
							aria-label="Edit title"
							title="Edit title"
						>
							{@render iconPencil()}
						</button>
					</div>
				{/if}

				<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">Note</p>
				{#if editingNote}
					<div class="flex flex-col gap-1.5">
						<textarea
							bind:value={noteDraft}
							rows="3"
							placeholder="Add a note - source, context, why you saved it..."
							class="border border-gray-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 rounded px-2 py-1 text-sm resize-none"
						></textarea>
						<div class="flex items-center gap-2">
							<button onclick={saveNote} disabled={savingNote} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
								{savingNote ? 'Saving...' : 'Save'}
							</button>
							<button onclick={() => { editingNote = false; noteDraft = inputText?.note ?? ''; }} disabled={savingNote} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
							{#if inputText.note}
								<button onclick={removeNote} disabled={savingNote} class="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-400 ml-auto">Delete</button>
							{/if}
						</div>
					</div>
				{:else if inputText.note}
					<p class="text-sm text-gray-700 dark:text-slate-300 whitespace-pre-wrap break-words mb-1.5">{inputText.note}</p>
					<button onclick={() => { editingNote = true; noteDraft = inputText?.note ?? ''; }} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300">Edit note</button>
				{:else}
					<button onclick={() => { editingNote = true; noteDraft = ''; }} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300">+ Add note</button>
				{/if}
			</div>

			<!-- Source text - the label/date/toggle row is always shown (mirrors
			     analyze/[id]'s own "Reading view" toggle, which stays visible
			     whichever of its two content modes is showing), with the
			     content below it swapping between the plain body paragraph
			     (real text nodes - selectable/copyable, no per-word buttons -
			     and this page's default) and ReadingView (segmented, colorable,
			     annotatable - see ReadingView.svelte's own docstring, which
			     anticipated exactly this embedding) once toggled on. The
			     toggle only appears once an analysis exists, since annotation
			     creation needs word occurrences to snap to and there's nothing
			     to switch into otherwise. -->
			<div class="mb-6">
				<div class="flex justify-between items-center mb-2">
					<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide">Source text</p>
					<div class="flex items-center gap-3">
						<p class="text-xs text-gray-400 dark:text-slate-500">
							Added {new Date(inputText.created_at).toLocaleDateString()}
						</p>
						{#if inputText.analyses.length > 0}
							<button
								type="button"
								onclick={() => readingViewOn = !readingViewOn}
								aria-pressed={readingViewOn}
								class="text-sm px-3 py-1.5 rounded-full border shrink-0 transition-colors {readingViewOn ? 'bg-blue-100 dark:bg-blue-500/15 border-blue-300 dark:border-blue-500/40 text-blue-700 dark:text-blue-400' : 'bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800'}"
							>
								Reading view
							</button>
						{/if}
					</div>
				</div>
				{#if readingViewOn && inputText.analyses.length > 0}
					<ReadingView analysisId={inputText.analyses[0].id} textTitle={inputText.title} analysisTitle={null} />
				{:else}
					<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6">
						<p class="whitespace-pre-wrap leading-relaxed text-gray-800 dark:text-slate-200">{inputText.body}</p>
					</div>
				{/if}
			</div>

			<!-- Analyses -->
			<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6">
				<div class="flex justify-between items-center mb-4">
					<h2 class="text-lg font-semibold text-gray-800 dark:text-slate-200">
						Analyses ({inputText.analyses.length})
					</h2>
					<button
						onclick={handleReanalyze}
						disabled={reanalyzing}
						class="bg-blue-600 dark:bg-blue-500 text-white px-4 py-2 rounded-md hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50 text-sm font-medium"
					>
						{reanalyzing ? 'Analyzing...' : '+ Re-analyze'}
					</button>
				</div>

				{#if inputText.analyses.length === 0}
					<p class="text-gray-400 dark:text-slate-500 text-sm">No analyses yet.</p>
				{:else}
					<div class="space-y-2">
						{#each inputText.analyses as analysis}
							<!-- Was a plain <a> wrapping the whole row - switched to a
							     div + click-passthrough (same handleRowClick/
							     handleCardClick pattern as the results table and the
							     home page's own text cards) once the row needed to
							     hold a second real interactive element (the trash
							     button below): a <button> nested inside an <a> is
							     invalid HTML and would also trigger the link's own
							     navigation on click. -->
							<div
								role="button"
								tabindex="0"
								onclick={(e) => { if ((e.target as HTMLElement).closest('button, a')) return; goto(`/analyze/${analysis.id}`); }}
								onkeydown={(e) => { if (e.key === 'Enter' && !(e.target as HTMLElement).closest('button, a')) goto(`/analyze/${analysis.id}`); }}
								class="flex justify-between items-center border border-gray-100 dark:border-slate-800 rounded-md px-4 py-3 hover:bg-gray-50 dark:hover:bg-slate-800 cursor-pointer"
							>
								<div>
									<p class="text-sm font-medium text-gray-800 dark:text-slate-200">
										{new Date(analysis.created_at).toLocaleString()}
									</p>
									<p class="text-xs text-gray-500 dark:text-slate-400 mt-0.5">
										{analysis.unique_words} unique words · {analysis.total_words} total
									</p>
								</div>
								<div class="flex items-center gap-3 shrink-0">
									<a href="/analyze/{analysis.id}" class="text-gray-600 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400" title="View results">
										{@render iconBarChart('w-7 h-7')}
										<span class="sr-only">View results</span>
									</a>
									<button
										onclick={() => handleDeleteAnalysis(analysis.id)}
										disabled={deletingAnalysisId === analysis.id}
										class="text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50"
										aria-label="Delete analysis"
										title="Delete analysis"
									>
										{@render iconTrashCan('w-7 h-7')}
									</button>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</main>
</div>
