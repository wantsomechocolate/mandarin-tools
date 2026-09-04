<script lang="ts">
	import * as api from '$lib/api';
	import { familiarityLabel, familiarityColor, rarityLabel, rarityColor } from '$lib/wordDisplay';
	import { isEntryEditable, type WordDetailContext } from '$lib/wordDetailContext';

	interface HskForm {
		traditional: string | null;
		pinyin: string | null;
		meanings: string[];
		classifiers: string[];
	}

	interface CedictSense {
		traditional: string | null;
		pinyin: string | null;
		definitions: string[];
	}

	interface SampleSentence {
		id: number;
		word: string;
		sentence: string;
	}

	// Both UserWordEntry/VisibilityEntry satisfy ScopedEntry (see
	// wordDetailContext.ts) structurally - no adapter needed for
	// isEntryEditable.
	interface UserWordEntry {
		id: number;
		scope: 'global' | 'text' | 'analysis';
		text_id: number | null;
		text_title: string | null;
		analysis_id: number | null;
		analysis_created_at: string | null;
		pronunciation: string | null;
		meaning: string | null;
		notes: string | null;
		affects_dag: boolean | null;
	}

	interface VisibilityEntry {
		id: number;
		scope: 'global' | 'text' | 'analysis';
		text_id: number | null;
		text_title: string | null;
		analysis_id: number | null;
		analysis_created_at: string | null;
		hidden: boolean;
	}

	interface WordDetail {
		word: string;
		familiarity: number | null;
		is_starred: boolean;
		is_garbage: boolean;
		frequency: number | null;
		freq_per_million: number | null;
		rarity_tier: string | null;
		hsk_v2_2012: number | null;
		hsk_v3_2021: number | null;
		hsk_v3_2026: number | null;
		forms: HskForm[];
		cedict: CedictSense[];
		sample_sentences: SampleSentence[];
		user_word_entries: UserWordEntry[];
		visibility_entries: VisibilityEntry[];
	}

	let {
		word,
		context,
		onClose,
		onUserWordEntriesChanged,
		onVisibilityEntriesChanged,
		onFamiliarityChanged,
	}: {
		word: string;
		context: WordDetailContext;
		onClose: () => void;
		// Fired after any UserWord/Visibility mutation with the fresh full
		// entries list, for a page that wants to keep its own state (e.g. the
		// results table's quick-action icons) in sync without a full refetch
		// of its own - see analyze/[id]/+page.svelte for the one consumer
		// that currently needs this. Optional: a page with nothing analogous
		// to patch (the profile list pages) can simply omit it.
		onUserWordEntriesChanged?: (entries: UserWordEntry[]) => void;
		onVisibilityEntriesChanged?: (entries: VisibilityEntry[]) => void;
		// Fired after Familiarity changes, with the new value - for the
		// profile Known Words list specifically, which shows exactly the
		// words with a familiarity score (a word with no row at all doesn't
		// appear there - see KnownWord's docstring, models.py) and so needs
		// to know the moment a word's score is cleared via the panel, not
		// just when the panel's own display updates.
		onFamiliarityChanged?: (familiarity: number | null) => void;
	} = $props();

	let detail = $state<WordDetail | null>(null);
	let loading = $state(true);
	let error = $state('');

	// Quick-action bar (Familiarity/Star/Garbage/global-UserWord) - always
	// global, always fully editable regardless of context (see KnownWord/
	// StarredWord's docstrings, models.py) - no hierarchy logic here.
	let updatingFamiliarity = $state(false);
	let togglingStarred = $state(false);
	let togglingGarbage = $state(false);
	let togglingGlobalUserWord = $state(false);

	let newSentenceDraft = $state('');
	let savingSentence = $state(false);
	let deletingSentenceId: number | null = $state(null);

	// UserWord section - collapsed-by-default text-/analysis-specific
	// groups (see the module docstring below the script for the layout
	// this implements), per-entry inline editing, and a "+ Add" affordance
	// for the current context's own text/analysis slot when nothing already
	// occupies it.
	let uwTextExpanded = $state(false);
	let uwAnalysisExpanded = $state(false);
	let uwEditingIds: Set<number> = $state(new Set());
	let uwDrafts: Record<number, { pronunciation: string; meaning: string; notes: string; affectsDag: boolean | null }> = $state({});
	let uwSavingId: number | null = $state(null);
	let uwAddingGlobal = $state(false);
	let uwAddingText = $state(false);
	let uwAddingAnalysis = $state(false);
	let uwNewDraft = $state<{ pronunciation: string; meaning: string; notes: string; affectsDag: boolean | null }>({ pronunciation: '', meaning: '', notes: '', affectsDag: true });

	// Visibility section - same collapsed-group pattern, but each entry is
	// just a Shown/Hidden toggle (no pronunciation/meaning/notes), and
	// unlike UserWord's affects_dag, ALL three scopes (including analysis)
	// are meaningfully editable - an analysis-scoped hidden override has a
	// real effect every time that exact analysis is reopened.
	let visTextExpanded = $state(false);
	let visAnalysisExpanded = $state(false);
	let visSavingId: number | null = $state(null);
	let visAddingGlobal = $state(false);
	let visAddingText = $state(false);
	let visAddingAnalysis = $state(false);

	async function load() {
		loading = true;
		error = '';
		uwEditingIds = new Set();
		uwDrafts = {};
		uwAddingGlobal = false;
		uwAddingText = false;
		uwAddingAnalysis = false;
		visAddingGlobal = false;
		visAddingText = false;
		visAddingAnalysis = false;
		try {
			detail = await api.getWordDetail(word) as WordDetail;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load word detail';
		} finally {
			loading = false;
		}
	}

	// Re-fetch whenever the word this panel is showing changes - the parent
	// keeps the same component instance mounted across word selections
	// (only `word`/`context` change), rather than remounting per word.
	$effect(() => {
		word;
		load();
	});

	const globalUserWord = $derived(detail?.user_word_entries.find((e: UserWordEntry) => e.scope === 'global') ?? null);
	const textUserWords = $derived(detail?.user_word_entries.filter((e: UserWordEntry) => e.scope === 'text') ?? []);
	const analysisUserWords = $derived(detail?.user_word_entries.filter((e: UserWordEntry) => e.scope === 'analysis') ?? []);
	const currentTextUserWord = $derived(
		context.type !== 'global' ? (textUserWords.find((e: UserWordEntry) => e.text_id === context.textId) ?? null) : null
	);
	const currentAnalysisUserWord = $derived(
		context.type === 'analysis' ? (analysisUserWords.find((e: UserWordEntry) => e.analysis_id === context.analysisId) ?? null) : null
	);

	const globalVisibility = $derived(detail?.visibility_entries.find((e: VisibilityEntry) => e.scope === 'global') ?? null);
	const textVisibility = $derived(detail?.visibility_entries.filter((e: VisibilityEntry) => e.scope === 'text') ?? []);
	const analysisVisibility = $derived(detail?.visibility_entries.filter((e: VisibilityEntry) => e.scope === 'analysis') ?? []);
	const currentTextVisibility = $derived(
		context.type !== 'global' ? (textVisibility.find((e: VisibilityEntry) => e.text_id === context.textId) ?? null) : null
	);
	const currentAnalysisVisibility = $derived(
		context.type === 'analysis' ? (analysisVisibility.find((e: VisibilityEntry) => e.analysis_id === context.analysisId) ?? null) : null
	);

	function entryLabel(entry: { scope: string; text_title: string | null; analysis_created_at: string | null }): string {
		if (entry.scope === 'global') return 'Global';
		if (entry.scope === 'text') return entry.text_title ?? 'Untitled text';
		const date = entry.analysis_created_at ? new Date(entry.analysis_created_at).toLocaleDateString() : '';
		return `Analysis of "${entry.text_title ?? 'Untitled text'}"${date ? ` (${date})` : ''}`;
	}

	function jumpLink(entry: { scope: string; text_id: number | null; analysis_id: number | null }): string | null {
		if (entry.scope === 'analysis' && entry.analysis_id != null) return `/analyze/${entry.analysis_id}`;
		if (entry.scope === 'text' && entry.text_id != null) return `/input-texts/${entry.text_id}`;
		return null;
	}

	function scopeContextFor(scope: 'global' | 'text' | 'analysis'): api.ScopeContext {
		if (scope === 'analysis' && context.type === 'analysis') return { analysisId: context.analysisId, scope: 'analysis' };
		if (scope === 'text' && context.type !== 'global') return { inputTextId: context.textId, scope: 'text' };
		return { scope: 'global' };
	}

	// Delete/exact-scope calls take raw (scopeAnalysisId, scopeInputTextId)
	// columns, not a ScopeContext - an entry's own text_id is populated even
	// for an analysis-scoped row (identifying which text that analysis
	// belongs to, for display/the editability hierarchy), but the
	// underlying row only ever has ONE of the two columns actually set (see
	// UserWord's docstring, models.py) - map from `scope` explicitly rather
	// than assuming text_id means "this row is text-scoped".
	function ownScopeIds(entry: { scope: string; text_id: number | null; analysis_id: number | null }): { scopeAnalysisId: number | null; scopeInputTextId: number | null } {
		if (entry.scope === 'analysis') return { scopeAnalysisId: entry.analysis_id, scopeInputTextId: null };
		if (entry.scope === 'text') return { scopeAnalysisId: null, scopeInputTextId: entry.text_id };
		return { scopeAnalysisId: null, scopeInputTextId: null };
	}

	async function refreshEntries() {
		await load();
		if (detail) {
			onUserWordEntriesChanged?.(detail.user_word_entries);
			onVisibilityEntriesChanged?.(detail.visibility_entries);
		}
	}

	// --- Quick-action bar: Familiarity / Star / Garbage / global UserWord --

	async function setFamiliarity(familiarity: number | null) {
		updatingFamiliarity = true;
		try {
			await api.upsertKnownWord(word, familiarity);
			if (detail) detail = { ...detail, familiarity };
			onFamiliarityChanged?.(familiarity);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update word';
		} finally {
			updatingFamiliarity = false;
		}
	}

	async function toggleStarred() {
		togglingStarred = true;
		try {
			if (detail?.is_starred) {
				await api.deleteStarredWord(word);
			} else {
				await api.createStarredWord(word);
			}
			if (detail) detail = { ...detail, is_starred: !detail.is_starred };
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update starred status';
		} finally {
			togglingStarred = false;
		}
	}

	async function toggleGarbage() {
		togglingGarbage = true;
		try {
			if (detail?.is_garbage) {
				await api.unmarkGarbageWord(word);
			} else {
				await api.createGarbageWord(word);
			}
			if (detail) detail = { ...detail, is_garbage: !detail.is_garbage };
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update garbage status';
		} finally {
			togglingGarbage = false;
		}
	}

	// The quick bookmark icon is a GLOBAL-only shortcut (add/remove the
	// global entry specifically) - the full UserWord section below is where
	// every scope, including text-/analysis-specific ones, is actually
	// managed. Consistent with "global entry always editable everywhere".
	async function toggleGlobalUserWord() {
		togglingGlobalUserWord = true;
		try {
			if (globalUserWord) {
				await api.deleteUserWord(word, null, null);
			} else {
				await api.createUserWord(word, undefined, { scope: 'global' });
			}
			await refreshEntries();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update your dictionary';
		} finally {
			togglingGlobalUserWord = false;
		}
	}

	// --- UserWord section ---------------------------------------------------

	function startEditingUserWord(entry: UserWordEntry) {
		uwDrafts = { ...uwDrafts, [entry.id]: {
			pronunciation: entry.pronunciation ?? '', meaning: entry.meaning ?? '', notes: entry.notes ?? '',
			affectsDag: entry.affects_dag,
		} };
		uwEditingIds = new Set([...uwEditingIds, entry.id]);
	}

	function cancelEditingUserWord(id: number) {
		const next = new Set(uwEditingIds);
		next.delete(id);
		uwEditingIds = next;
	}

	async function saveUserWordEntry(entry: UserWordEntry) {
		uwSavingId = entry.id;
		try {
			const draft = uwDrafts[entry.id];
			const isAnalysisScoped = entry.scope === 'analysis';
			const fields: { pronunciation: string | null; meaning: string | null; notes: string | null; affects_dag?: boolean | null } = {
				pronunciation: draft.pronunciation || null,
				meaning: draft.meaning || null,
				notes: draft.notes || null,
			};
			// affects_dag is never sent for an analysis-scoped entry - it has
			// no observable effect there (see UserWord's docstring, models.py).
			if (!isAnalysisScoped) fields.affects_dag = draft.affectsDag;
			await api.upsertUserWordDetail(word, fields, scopeContextForExistingEntry(entry));
			cancelEditingUserWord(entry.id);
			await refreshEntries();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to save word details';
		} finally {
			uwSavingId = null;
		}
	}

	function scopeContextForExistingEntry(entry: { scope: string; text_id: number | null; analysis_id: number | null }): api.ScopeContext {
		if (entry.scope === 'analysis') return { analysisId: entry.analysis_id!, scope: 'analysis' };
		if (entry.scope === 'text') return { inputTextId: entry.text_id!, scope: 'text' };
		return { scope: 'global' };
	}

	async function deleteUserWordEntry(entry: UserWordEntry) {
		uwSavingId = entry.id;
		try {
			const ids = ownScopeIds(entry);
			await api.deleteUserWord(word, ids.scopeAnalysisId, ids.scopeInputTextId);
			await refreshEntries();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove word from your dictionary';
		} finally {
			uwSavingId = null;
		}
	}

	function startAddingUserWord(scope: 'global' | 'text' | 'analysis') {
		uwNewDraft = { pronunciation: '', meaning: '', notes: '', affectsDag: true };
		if (scope === 'global') uwAddingGlobal = true;
		else if (scope === 'text') uwAddingText = true;
		else uwAddingAnalysis = true;
	}

	function cancelAddingUserWord(scope: 'global' | 'text' | 'analysis') {
		if (scope === 'global') uwAddingGlobal = false;
		else if (scope === 'text') uwAddingText = false;
		else uwAddingAnalysis = false;
	}

	async function saveNewUserWord(scope: 'global' | 'text' | 'analysis') {
		uwSavingId = -1;
		try {
			const isAnalysisScoped = scope === 'analysis';
			const fields: { pronunciation: string | null; meaning: string | null; notes: string | null; affects_dag?: boolean | null } = {
				pronunciation: uwNewDraft.pronunciation || null,
				meaning: uwNewDraft.meaning || null,
				notes: uwNewDraft.notes || null,
			};
			if (!isAnalysisScoped) fields.affects_dag = uwNewDraft.affectsDag;
			await api.upsertUserWordDetail(word, fields, scopeContextFor(scope));
			cancelAddingUserWord(scope);
			await refreshEntries();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add word to your dictionary';
		} finally {
			uwSavingId = null;
		}
	}

	// --- Visibility section --------------------------------------------------

	async function setVisibility(entry: VisibilityEntry | 'new-global' | 'new-text' | 'new-analysis', hidden: boolean) {
		const scope: 'global' | 'text' | 'analysis' =
			entry === 'new-global' ? 'global' : entry === 'new-text' ? 'text' : entry === 'new-analysis' ? 'analysis'
			: (entry.scope as 'global' | 'text' | 'analysis');
		const id = typeof entry === 'string' ? -1 : entry.id;
		visSavingId = id;
		try {
			const ctx = typeof entry === 'string' ? scopeContextFor(scope) : scopeContextForExistingEntry(entry);
			await api.upsertWordVisibility(word, hidden, ctx);
			visAddingGlobal = false;
			visAddingText = false;
			visAddingAnalysis = false;
			await refreshEntries();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update visibility';
		} finally {
			visSavingId = null;
		}
	}

	async function removeVisibilityEntry(entry: VisibilityEntry) {
		visSavingId = entry.id;
		try {
			const ids = ownScopeIds(entry);
			await api.deleteWordVisibility(word, ids.scopeAnalysisId, ids.scopeInputTextId);
			await refreshEntries();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove visibility override';
		} finally {
			visSavingId = null;
		}
	}

	async function addSampleSentence() {
		const sentence = newSentenceDraft.trim();
		if (!sentence) return;
		savingSentence = true;
		try {
			const created = await api.addSampleSentence(word, sentence) as SampleSentence;
			if (detail) detail = { ...detail, sample_sentences: [...detail.sample_sentences, created] };
			newSentenceDraft = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add sample sentence';
		} finally {
			savingSentence = false;
		}
	}

	async function removeSampleSentence(sentenceId: number) {
		deletingSentenceId = sentenceId;
		try {
			await api.deleteSampleSentence(sentenceId);
			if (detail) detail = { ...detail, sample_sentences: detail.sample_sentences.filter((s) => s.id !== sentenceId) };
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove sample sentence';
		} finally {
			deletingSentenceId = null;
		}
	}

</script>

<!--
	WordDetailPanel: the shared side-panel shown for a single word, used by
	the analyze/[id] results page and the profile known-words/user-words/
	starred-words list pages (see each for how it's opened).

	`context` is who's asking, not what to show - the panel always fetches
	and displays EVERY UserWord/WordVisibility entry that exists for this
	word, across every scope this user has ever customized it in (not
	bounded at 3, not resolved against `context`). `context` only decides
	which of those entries are editable here vs. read-only-with-a-jump-link -
	see isEntryEditable (wordDetailContext.ts) for the exact hierarchy rule.

	Layout for both the UserWord and Visibility sections (the only two
	sections this rule applies to - Dictionary/HSK/CC-CEDICT are pure
	read-only reference data, and Known/Starred/Garbage are already
	global-only by design, always fully editable, no hierarchy needed):
	  - Global entry always shown first, in full, always editable.
	  - Text-specific entries collapse into a "Text-specific (N)" summary,
	    expandable to the full list - each row editable or read-only+jump-
	    link per isEntryEditable. Omitted entirely when there are none.
	  - Analysis-specific entries: same pattern, "Analysis-specific (N)".
	  - A "+ Add ... for this text/analysis" affordance appears next to the
	    relevant group when `context` provides a textId/analysisId that
	    doesn't already have an entry - lets a customization still be
	    scoped to exactly what's currently being viewed, same as before
	    this rework, just reframed around the flat list.

	In `{ type: 'global' }` context (no textId/analysisId at all), every
	text-/analysis-scoped entry is read-only and neither "+ Add for this
	text/analysis" affordance appears - this falls out of isEntryEditable's
	rule with no special case, not a separate "global page" branch.
-->
<div class="w-full lg:w-72 max-h-[85vh] overflow-y-auto bg-white rounded-t-2xl lg:rounded-lg shadow-sm p-4">
	{#if loading}
		<p class="text-gray-500 text-sm">Loading...</p>
	{:else if error && !detail}
		<div class="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm mb-2">{error}</div>
		<button onclick={onClose} class="text-sm text-gray-500 hover:text-gray-700">Close</button>
	{:else if detail}
		<div class="flex justify-between items-start mb-3">
			<h2 class="text-3xl font-medium">{detail.word}</h2>
			<button onclick={onClose} class="text-gray-400 hover:text-gray-600">✕</button>
		</div>

		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm mb-3">{error}</div>
		{/if}

		<!-- Familiarity + quick actions - always global, always fully
		     editable regardless of context (see KnownWord/StarredWord's
		     docstrings, models.py). -->
		<div class="border-b border-gray-100 mb-4 pb-4">
			<div class="flex flex-wrap gap-1 mb-2">
				{#each [1, 2, 3, 4, 5] as score}
					<button
						onclick={() => setFamiliarity(score)}
						disabled={updatingFamiliarity}
						class="w-8 h-8 rounded text-xs font-medium disabled:opacity-50
						{detail.familiarity === score ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
					>
						{score}
					</button>
				{/each}
				{#if detail.familiarity !== null}
					<button
						onclick={() => setFamiliarity(null)}
						disabled={updatingFamiliarity}
						class="w-8 h-8 rounded text-xs font-medium bg-gray-100 text-gray-400 hover:bg-gray-200 disabled:opacity-50"
					>
						✕
					</button>
				{/if}
			</div>
			<div class="flex flex-wrap items-center gap-0.5">
				<button
					onclick={toggleGlobalUserWord}
					disabled={togglingGlobalUserWord}
					class="p-1.5 rounded {globalUserWord ? 'text-emerald-600' : 'text-gray-400'} hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50"
					title={globalUserWord ? 'In your dictionary globally — click to remove' : 'Add to your custom dictionary globally'}
					aria-label="Global dictionary entry"
				>
					<svg class="w-4 h-4" viewBox="0 0 20 20" fill={globalUserWord ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.3">
						<path d="M5 3.5A1.5 1.5 0 0 1 6.5 2h7A1.5 1.5 0 0 1 15 3.5v13l-5-3-5 3v-13Z" stroke-linejoin="round" />
					</svg>
				</button>
				<button
					onclick={toggleStarred}
					disabled={togglingStarred}
					class="p-1.5 rounded {detail.is_starred ? 'text-amber-500' : 'text-gray-400'} hover:text-amber-500 hover:bg-amber-50 disabled:opacity-50"
					title={detail.is_starred ? 'Starred — click to unstar' : 'Star as interesting'}
					aria-label="Starred"
				>
					<svg class="w-4 h-4" viewBox="0 0 20 20" fill={detail.is_starred ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.3" stroke-linejoin="round">
						<path d="M10 2.5l2.2 4.6 5 .7-3.6 3.6.85 5-4.45-2.4-4.45 2.4.85-5-3.6-3.6 5-.7L10 2.5Z" />
					</svg>
				</button>
				<button
					onclick={toggleGarbage}
					disabled={togglingGarbage}
					class="p-1.5 rounded {detail.is_garbage ? 'text-red-600' : 'text-gray-400'} hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
					title={detail.is_garbage ? 'Marked as garbage — click to unmark' : 'Mark as garbage'}
					aria-label="Garbage"
				>
					<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<path d="M4 5.5h12M8 5.5V4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5M6 5.5l.6 10.2a1 1 0 0 0 1 .8h4.8a1 1 0 0 0 1-.8l.6-10.2M8.5 8.5v5M11.5 8.5v5" />
					</svg>
				</button>
			</div>
		</div>

		<!-- Corpus frequency -->
		<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Corpus frequency</p>
		{#if detail.rarity_tier}
			<span
				class="text-xs px-2 py-1 rounded-full {rarityColor(detail.rarity_tier)}"
				title={detail.frequency != null && detail.freq_per_million != null
					? `${detail.frequency.toLocaleString()} occurrences (${detail.freq_per_million.toFixed(detail.freq_per_million < 1 ? 4 : 2)} per million)`
					: ''}
			>
				{rarityLabel(detail.rarity_tier)}
			</span>
		{:else}
			<p class="text-sm text-gray-400">No frequency data for this word.</p>
		{/if}

		<!-- HSK -->
		<div class="border-t border-gray-100 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">HSK</p>

			{#if detail.hsk_v2_2012 || detail.hsk_v3_2021 || detail.hsk_v3_2026 || detail.forms.length > 0}
				<div class="flex flex-wrap gap-1 mb-3">
					{#if detail.hsk_v2_2012}
						<span class="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded-full">HSK 2012: {detail.hsk_v2_2012}</span>
					{/if}
					{#if detail.hsk_v3_2021}
						<span class="text-xs px-2 py-1 bg-purple-100 text-purple-700 rounded-full">HSK 2021: {detail.hsk_v3_2021}</span>
					{/if}
					{#if detail.hsk_v3_2026}
						<span class="text-xs px-2 py-1 bg-green-100 text-green-700 rounded-full">HSK 2026: {detail.hsk_v3_2026}</span>
					{/if}
				</div>

				{#if detail.forms.length > 0}
					<div class="space-y-3">
						{#each detail.forms as form, i}
							<div class="{i > 0 ? 'border-t border-gray-100 pt-3' : ''}">
								{#if detail.forms.length > 1}
									<p class="text-xs text-gray-400 mb-1">Form {i + 1}</p>
								{/if}
								{#if form.traditional && form.traditional !== detail.word}
									<p class="text-sm text-gray-600 mb-1">
										Traditional: <span class="font-medium">{form.traditional}</span>
									</p>
								{/if}
								{#if form.pinyin}
									<p class="text-sm text-blue-600 mb-1">{form.pinyin}</p>
								{/if}
								{#if form.meanings.length > 0}
									<ul class="text-sm text-gray-700 space-y-0.5">
										{#each form.meanings as meaning}
											<li>• {meaning}</li>
										{/each}
									</ul>
								{/if}
								{#if form.classifiers.length > 0}
									<p class="text-xs text-gray-500 mt-1">Classifiers: {form.classifiers.join(', ')}</p>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			{:else}
				<p class="text-sm text-gray-400">No HSK entry for this word.</p>
			{/if}
		</div>

		<!-- CC-CEDICT -->
		<div class="border-t border-gray-100 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">CC-CEDICT</p>

			{#if detail.cedict.length > 0}
				<div class="space-y-3">
					{#each detail.cedict as sense, i}
						<div class="{i > 0 ? 'border-t border-gray-100 pt-3' : ''}">
							{#if detail.cedict.length > 1}
								<p class="text-xs text-gray-400 mb-1">Sense {i + 1}</p>
							{/if}
							{#if sense.traditional && sense.traditional !== detail.word}
								<p class="text-sm text-gray-600 mb-1">
									Traditional: <span class="font-medium">{sense.traditional}</span>
								</p>
							{/if}
							{#if sense.pinyin}
								<p class="text-sm text-blue-600 mb-1">{sense.pinyin}</p>
							{/if}
							{#if sense.definitions.length > 0}
								<ul class="text-sm text-gray-700 space-y-0.5">
									{#each sense.definitions as definition}
										<li>• {definition}</li>
									{/each}
								</ul>
							{/if}
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-sm text-gray-400">No CC-CEDICT entry for this word.</p>
			{/if}
		</div>

		<!-- Your entries (UserWord) -->
		<div class="border-t border-gray-100 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Your entries</p>

			{#snippet uwFields(draftKey: string, draft: { pronunciation: string; meaning: string; notes: string; affectsDag: boolean | null }, showAffectsDag: boolean, idPrefix: string)}
				<div class="space-y-2">
					<div>
						<label for="{idPrefix}-pron" class="text-xs text-gray-500">Pronunciation</label>
						<input id="{idPrefix}-pron" type="text" bind:value={draft.pronunciation} placeholder="e.g. dà yě láng" class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5" />
					</div>
					<div>
						<label for="{idPrefix}-meaning" class="text-xs text-gray-500">
							Meaning / definition
							<span class="text-gray-400 font-normal">- separate senses with "/", CC-CEDICT style</span>
						</label>
						<textarea id="{idPrefix}-meaning" bind:value={draft.meaning} placeholder="to run/to flee/(of a horse) to gallop" rows="2" class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"></textarea>
					</div>
					<div>
						<label for="{idPrefix}-notes" class="text-xs text-gray-500">Notes</label>
						<textarea id="{idPrefix}-notes" bind:value={draft.notes} placeholder="Any other notes — context, mnemonics, etc." rows="2" class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"></textarea>
					</div>
					{#if showAffectsDag}
						<!-- Tri-state, not a checkbox - NULL ("no preference") is a
						     real, distinct value from false ("excluded"), not just
						     "unchecked" - see UserWord.affects_dag's docstring
						     (models.py). Hidden for an analysis-scoped entry - it
						     can never have an observable effect there. -->
						<div class="text-xs text-gray-500">
							<span class="block mb-1">Segmentation weight</span>
							<label class="flex items-center gap-1.5 mb-0.5">
								<input type="radio" name="{idPrefix}-affects-dag" checked={draft.affectsDag === true} onchange={() => draft.affectsDag = true} />
								Affects segmentation
							</label>
							<label class="flex items-center gap-1.5 mb-0.5">
								<input type="radio" name="{idPrefix}-affects-dag" checked={draft.affectsDag === false} onchange={() => draft.affectsDag = false} />
								Excluded from segmentation
							</label>
							<label class="flex items-center gap-1.5">
								<input type="radio" name="{idPrefix}-affects-dag" checked={draft.affectsDag === null} onchange={() => draft.affectsDag = null} />
								No preference (inherit from broader scope)
							</label>
						</div>
					{/if}
				</div>
			{/snippet}

			{#snippet uwEntryCard(entry: UserWordEntry)}
				{@const editing = uwEditingIds.has(entry.id)}
				{@const editable = isEntryEditable(entry, context)}
				{@const link = jumpLink(entry)}
				<div class="mb-2 pb-2 border-b border-gray-50 last:border-0">
					<div class="flex justify-between items-center mb-1 gap-2">
						<span class="text-xs font-medium text-gray-500 truncate">{entryLabel(entry)}</span>
						{#if editable}
							<div class="flex gap-2 shrink-0">
								{#if !editing}
									<button onclick={() => startEditingUserWord(entry)} class="text-xs text-blue-600 hover:text-blue-800">Edit</button>
								{/if}
								<button onclick={() => deleteUserWordEntry(entry)} disabled={uwSavingId === entry.id} class="text-xs text-red-400 hover:text-red-600 disabled:opacity-50">Delete</button>
							</div>
						{:else if link}
							<a href={link} class="text-xs text-blue-600 hover:text-blue-800 shrink-0">View →</a>
						{/if}
					</div>

					{#if editing}
						{@render uwFields(`entry-${entry.id}`, uwDrafts[entry.id], entry.scope !== 'analysis', `uw-${entry.id}`)}
						<div class="flex gap-2 pt-1">
							<button onclick={() => saveUserWordEntry(entry)} disabled={uwSavingId === entry.id} class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
								{uwSavingId === entry.id ? 'Saving...' : 'Save'}
							</button>
							<button onclick={() => cancelEditingUserWord(entry.id)} disabled={uwSavingId === entry.id} class="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700">Cancel</button>
						</div>
					{:else}
						<div class="space-y-1">
							{#if entry.pronunciation}<p class="text-sm text-blue-600">{entry.pronunciation}</p>{/if}
							{#if entry.meaning}<p class="text-sm text-gray-700">{entry.meaning}</p>{/if}
							{#if entry.notes}<p class="text-xs text-gray-500 italic">{entry.notes}</p>{/if}
							{#if !entry.pronunciation && !entry.meaning && !entry.notes}<p class="text-sm text-gray-400">No details added yet.</p>{/if}
							{#if entry.scope !== 'analysis' && entry.affects_dag === false}
								<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">Excluded from segmentation</span>
							{:else if entry.scope !== 'analysis' && entry.affects_dag === null}
								<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-400">No segmentation preference (inherits)</span>
							{/if}
							{#if !editable}
								<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">Read-only from here</span>
							{/if}
						</div>
					{/if}
				</div>
			{/snippet}

			<!-- Global - always shown, always editable. -->
			{#if globalUserWord}
				{@render uwEntryCard(globalUserWord)}
			{:else if uwAddingGlobal}
				<div class="mb-2 pb-2 border-b border-gray-50">
					<span class="text-xs font-medium text-gray-500">Global</span>
					{@render uwFields('new-global', uwNewDraft, true, 'uw-new-global')}
					<div class="flex gap-2 pt-1">
						<button onclick={() => saveNewUserWord('global')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
							{uwSavingId === -1 ? 'Saving...' : 'Save'}
						</button>
						<button onclick={() => cancelAddingUserWord('global')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700">Cancel</button>
					</div>
				</div>
			{:else}
				<button onclick={() => startAddingUserWord('global')} class="text-xs text-blue-600 hover:text-blue-800 mb-2">+ Add global entry</button>
			{/if}

			<!-- Text-specific -->
			{#if textUserWords.length > 0}
				<button onclick={() => uwTextExpanded = !uwTextExpanded} class="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 mt-1">
					<span class="transition-transform {uwTextExpanded ? 'rotate-90' : ''}">▸</span>
					Text-specific ({textUserWords.length})
				</button>
				{#if uwTextExpanded}
					<div class="mt-1 pl-2 border-l-2 border-gray-100">
						{#each textUserWords as entry (entry.id)}
							{@render uwEntryCard(entry)}
						{/each}
					</div>
				{/if}
			{/if}
			{#if context.type !== 'global' && !currentTextUserWord}
				{#if uwAddingText}
					<div class="mb-2 pb-2 border-b border-gray-50 mt-1">
						<span class="text-xs font-medium text-gray-500">{context.textTitle ?? 'This text'}</span>
						{@render uwFields('new-text', uwNewDraft, true, 'uw-new-text')}
						<div class="flex gap-2 pt-1">
							<button onclick={() => saveNewUserWord('text')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
								{uwSavingId === -1 ? 'Saving...' : 'Save'}
							</button>
							<button onclick={() => cancelAddingUserWord('text')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700">Cancel</button>
						</div>
					</div>
				{:else}
					<button onclick={() => startAddingUserWord('text')} class="text-xs text-blue-600 hover:text-blue-800 mt-1 block">+ Add entry for this text</button>
				{/if}
			{/if}

			<!-- Analysis-specific -->
			{#if analysisUserWords.length > 0}
				<button onclick={() => uwAnalysisExpanded = !uwAnalysisExpanded} class="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 mt-2">
					<span class="transition-transform {uwAnalysisExpanded ? 'rotate-90' : ''}">▸</span>
					Analysis-specific ({analysisUserWords.length})
				</button>
				{#if uwAnalysisExpanded}
					<div class="mt-1 pl-2 border-l-2 border-gray-100">
						{#each analysisUserWords as entry (entry.id)}
							{@render uwEntryCard(entry)}
						{/each}
					</div>
				{/if}
			{/if}
			{#if context.type === 'analysis' && !currentAnalysisUserWord}
				{#if uwAddingAnalysis}
					<div class="mb-2 pb-2 border-b border-gray-50 mt-1">
						<span class="text-xs font-medium text-gray-500">This analysis</span>
						{@render uwFields('new-analysis', uwNewDraft, false, 'uw-new-analysis')}
						<div class="flex gap-2 pt-1">
							<button onclick={() => saveNewUserWord('analysis')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
								{uwSavingId === -1 ? 'Saving...' : 'Save'}
							</button>
							<button onclick={() => cancelAddingUserWord('analysis')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700">Cancel</button>
						</div>
					</div>
				{:else}
					<button onclick={() => startAddingUserWord('analysis')} class="text-xs text-blue-600 hover:text-blue-800 mt-2 block">+ Add entry for this analysis</button>
				{/if}
			{/if}
		</div>

		<!-- Sample sentences - independent of Your entries above (see
		     SampleSentence's docstring, models.py) - global per user+word,
		     no scoping, so unaffected by this change. -->
		<div class="border-t border-gray-100 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Sample sentences</p>

			{#if detail.sample_sentences.length}
				<ul class="space-y-1.5 mb-2">
					{#each detail.sample_sentences as s (s.id)}
						<li class="flex items-start justify-between gap-2">
							<p class="text-sm text-gray-700">{s.sentence}</p>
							<button onclick={() => removeSampleSentence(s.id)} disabled={deletingSentenceId === s.id} class="text-gray-300 hover:text-red-600 disabled:opacity-50 shrink-0" title="Remove sample sentence" aria-label="Remove sample sentence">✕</button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="text-sm text-gray-400 mb-2">No sample sentences yet.</p>
			{/if}

			<div class="flex gap-1">
				<input
					type="text"
					bind:value={newSentenceDraft}
					placeholder="Paste an example sentence..."
					class="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
					onkeydown={(e) => { if (e.key === 'Enter') addSampleSentence(); }}
				/>
				<button onclick={addSampleSentence} disabled={!newSentenceDraft.trim() || savingSentence} class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 shrink-0">
					{savingSentence ? '...' : 'Add'}
				</button>
			</div>
		</div>

		<!-- Visibility ("hide from results") - same layout pattern as Your
		     entries above, but ALL three scopes (including analysis) are
		     meaningfully editable here - an analysis-scoped hidden override
		     has a real effect every time that exact analysis is reopened,
		     unlike an analysis-scoped affects_dag (see UserWord's docstring,
		     models.py). Placed last, not grouped with the dictionary-ish
		     sections above. -->
		<div class="border-t border-gray-100 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Visibility</p>

			{#snippet visEntryRow(entry: VisibilityEntry)}
				{@const editable = isEntryEditable(entry, context)}
				{@const link = jumpLink(entry)}
				<div class="flex items-center justify-between gap-2 py-1">
					<span class="text-xs text-gray-500 truncate">{entryLabel(entry)}</span>
					{#if editable}
						<div class="flex items-center gap-2 shrink-0">
							<button
								onclick={() => setVisibility(entry, !entry.hidden)}
								disabled={visSavingId === entry.id}
								class="text-xs px-2 py-1 rounded-full disabled:opacity-50 {entry.hidden ? 'bg-slate-200 text-slate-700' : 'bg-emerald-100 text-emerald-700'}"
							>
								{entry.hidden ? 'Hidden' : 'Shown'}
							</button>
							<button onclick={() => removeVisibilityEntry(entry)} disabled={visSavingId === entry.id} class="text-xs text-red-400 hover:text-red-600 disabled:opacity-50">
								Remove
							</button>
						</div>
					{:else}
						<div class="flex items-center gap-2 shrink-0">
							<span class="text-xs px-2 py-1 rounded-full {entry.hidden ? 'bg-slate-100 text-slate-600' : 'bg-gray-100 text-gray-500'}">
								{entry.hidden ? 'Hidden' : 'Shown'}
							</span>
							{#if link}<a href={link} class="text-xs text-blue-600 hover:text-blue-800">View →</a>{/if}
						</div>
					{/if}
				</div>
			{/snippet}

			{#snippet visAddRow(scope: 'global' | 'text' | 'analysis', label: string, adding: boolean, setAdding: (v: boolean) => void, newKey: 'new-global' | 'new-text' | 'new-analysis')}
				<div class="flex items-center justify-between gap-2 py-1">
					<span class="text-xs text-gray-500 truncate">{label}</span>
					{#if adding}
						<div class="flex items-center gap-1 shrink-0">
							<button onclick={() => setVisibility(newKey, false)} disabled={visSavingId === -1} class="text-xs px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 hover:bg-emerald-200 disabled:opacity-50">Shown</button>
							<button onclick={() => setVisibility(newKey, true)} disabled={visSavingId === -1} class="text-xs px-2 py-1 rounded-full bg-slate-200 text-slate-700 hover:bg-slate-300 disabled:opacity-50">Hidden</button>
							<button onclick={() => setAdding(false)} class="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
						</div>
					{:else}
						<div class="flex items-center gap-2 shrink-0">
							<span class="text-xs text-gray-400">Not set - inherits</span>
							<button onclick={() => setAdding(true)} class="text-xs text-blue-600 hover:text-blue-800">+ Override</button>
						</div>
					{/if}
				</div>
			{/snippet}

			<!-- Global -->
			{#if globalVisibility}
				{@render visEntryRow(globalVisibility)}
			{:else}
				{@render visAddRow('global', 'Global', visAddingGlobal, (v) => visAddingGlobal = v, 'new-global')}
			{/if}

			<!-- Text-specific -->
			{#if textVisibility.length > 0}
				<button onclick={() => visTextExpanded = !visTextExpanded} class="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 mt-1">
					<span class="transition-transform {visTextExpanded ? 'rotate-90' : ''}">▸</span>
					Text-specific ({textVisibility.length})
				</button>
				{#if visTextExpanded}
					<div class="mt-1 pl-2 border-l-2 border-gray-100">
						{#each textVisibility as entry (entry.id)}
							{@render visEntryRow(entry)}
						{/each}
					</div>
				{/if}
			{/if}
			{#if context.type !== 'global' && !currentTextVisibility}
				{@render visAddRow('text', context.textTitle ?? 'This text', visAddingText, (v) => visAddingText = v, 'new-text')}
			{/if}

			<!-- Analysis-specific -->
			{#if analysisVisibility.length > 0}
				<button onclick={() => visAnalysisExpanded = !visAnalysisExpanded} class="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 mt-2">
					<span class="transition-transform {visAnalysisExpanded ? 'rotate-90' : ''}">▸</span>
					Analysis-specific ({analysisVisibility.length})
				</button>
				{#if visAnalysisExpanded}
					<div class="mt-1 pl-2 border-l-2 border-gray-100">
						{#each analysisVisibility as entry (entry.id)}
							{@render visEntryRow(entry)}
						{/each}
					</div>
				{/if}
			{/if}
			{#if context.type === 'analysis' && !currentAnalysisVisibility}
				{@render visAddRow('analysis', 'This analysis', visAddingAnalysis, (v) => visAddingAnalysis = v, 'new-analysis')}
			{/if}
		</div>
	{/if}
</div>
