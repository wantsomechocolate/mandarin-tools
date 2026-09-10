<script lang="ts">
	import * as api from '$lib/api';
	import { familiarityLabel, familiarityColor, rarityLabel, rarityColor } from '$lib/wordDisplay';
	import { isEntryEditable, type WordDetailContext } from '$lib/wordDetailContext';
	import { saveWordDraft, loadWordDraft, clearWordDraft } from '$lib/wordDraftPersistence';
	import FamiliarityDots from './FamiliarityDots.svelte';

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

	// Re-exported from api.ts (see its docstring there) so every type
	// annotation in this file can say `AffectsDag` instead of `api.AffectsDag`.
	type AffectsDag = api.AffectsDag;

	// Both UserWordEntry/VisibilityEntry satisfy ScopedEntry (see
	// wordDetailContext.ts) structurally - no adapter needed for
	// isEntryEditable. Exported so WordDetailModal.svelte (the shared
	// wrapper around this component) can mirror these callback param types
	// exactly rather than re-declaring them by hand.
	export interface UserWordEntry {
		id: number;
		scope: 'global' | 'text' | 'analysis';
		text_id: number | null;
		text_title: string | null;
		analysis_id: number | null;
		analysis_created_at: string | null;
		pronunciation: string | null;
		meaning: string | null;
		notes: string | null;
		affects_dag: AffectsDag | null;
	}

	export interface VisibilityEntry {
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
		// A word's single free-text note, if any - see WordNote's docstring,
		// models.py. Null means no note exists, not "note is an empty
		// string" (an empty note is never persisted - see saveNote below).
		note: string | null;
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
		onNoteChanged,
		onGarbageMarked,
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
		// Fired after the note is saved/cleared, with the new value (null if
		// cleared) - for the profile Notes list specifically, which shows
		// exactly the words with a note (a word with no WordNote row doesn't
		// appear there - see WordNote's docstring, models.py) and so needs to
		// know the moment a note is cleared via the panel, same reasoning as
		// onFamiliarityChanged above for Known Words.
		onNoteChanged?: (note: string | null) => void;
		// Fired when this word transitions to is_garbage=true - garbage now
		// takes precedence as a read-time filter on the Known/User/Starred
		// Words listings (see list_known_words/list_user_words/
		// list_starred_words, router.py), so a list page showing this word
		// needs to drop it immediately rather than waiting for a reload.
		// Nothing fires on unmark - a word becoming visible again on a list
		// it's currently not excluded from doesn't need to appear without a
		// refresh (see this feature's spec). Single point of firing, so a
		// future undo affordance has one place to hook rather than several.
		onGarbageMarked?: () => void;
	} = $props();

	let detail = $state<WordDetail | null>(null);
	let loading = $state(true);
	let error = $state('');

	// Auto-generated (pinyin/translation) - see WordEnrichment's docstring
	// (models.py, backend). Fetched independently of `detail` above (not
	// awaited together) since it's a secondary concern that shouldn't hold
	// back the panel's main content, same "fired independently" reasoning
	// word-lists/+page.svelte's own count-loading already uses.
	interface WordEnrichment {
		word: string;
		pinyin: string | null;
		translation: string | null;
		google_translation: string | null;
		ctranslate2_translation: string | null;
		ctranslate2_stale: boolean;
	}
	let enrichment = $state<WordEnrichment | null>(null);
	let enrichmentLoading = $state(true);
	let enrichmentGenerating = $state(false);
	let enrichmentError = $state('');

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

	// Note - single free-text field, upsert-typed like Familiarity, not
	// list-typed like sample sentences above.
	let editingNote = $state(false);
	let noteDraft = $state('');
	let savingNote = $state(false);

	// UserWord section - collapsed-by-default text-/analysis-specific
	// groups (see the module docstring below the script for the layout
	// this implements), per-entry inline editing, and a "+ Add" affordance
	// for the current context's own text/analysis slot when nothing already
	// occupies it.
	let uwTextExpanded = $state(false);
	let uwAnalysisExpanded = $state(false);
	let uwEditingIds: Set<number> = $state(new Set());
	let uwDrafts: Record<number, { pronunciation: string; meaning: string; notes: string; affectsDag: AffectsDag | null }> = $state({});
	let uwSavingId: number | null = $state(null);
	let uwAddingGlobal = $state(false);
	let uwAddingText = $state(false);
	let uwAddingAnalysis = $state(false);
	let uwNewDraft = $state<{ pronunciation: string; meaning: string; notes: string; affectsDag: AffectsDag | null }>({ pronunciation: '', meaning: '', notes: '', affectsDag: 'increase' });

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

	// Tracks which word draft-restoration has already run for, so it fires
	// exactly once per genuine visit to a word - see load()'s own comment
	// below for why this can't just be "every call to load()". Plain
	// (non-$state) - this is internal bookkeeping load() reads/writes
	// itself, never read reactively/from the template.
	let restoredDraftForWord: string | null = null;

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
		editingNote = false;
		noteDraft = '';
		newSentenceDraft = '';
		// Restore an in-progress draft for this word, if one was saved before
		// an interruption (e.g. a mobile browser discarding/reloading the page
		// while backgrounded - see wordDraftPersistence.ts's docstring).
		// Applied AFTER the resets above so a genuine switch to a different
		// word (no saved draft for it) still starts clean, exactly as before.
		//
		// Gated to run only the FIRST time load() runs for this particular
		// word, not on every call - load() is also called directly by
		// refreshEntries() after a save/delete, on the SAME word, and by
		// then the draft has already been (or is about to be) cleared by
		// the persistence $effect below reacting to cancelEditingUserWord's
		// own reset. Without this gate, restoring unconditionally here would
		// race that clear - reading sessionStorage before the effect has
		// flushed - and immediately reopen the just-saved edit form with the
		// stale pre-save draft, undoing the save.
		if (restoredDraftForWord !== word) {
			restoredDraftForWord = word;
			const savedDraft = loadWordDraft(word);
			if (savedDraft) {
				newSentenceDraft = savedDraft.newSentenceDraft;
				editingNote = savedDraft.editingNote;
				noteDraft = savedDraft.noteDraft;
				uwAddingGlobal = savedDraft.uwAddingGlobal;
				uwAddingText = savedDraft.uwAddingText;
				uwAddingAnalysis = savedDraft.uwAddingAnalysis;
				uwNewDraft = savedDraft.uwNewDraft;
				uwEditingIds = new Set(savedDraft.uwEditingIds);
				uwDrafts = savedDraft.uwDrafts;
			}
		}
		try {
			detail = await api.getWordDetail(word) as WordDetail;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load word detail';
		} finally {
			loading = false;
		}
	}

	async function loadEnrichment() {
		enrichmentLoading = true;
		enrichmentError = '';
		try {
			enrichment = await api.getWordEnrichment(word) as WordEnrichment;
		} catch (e: unknown) {
			enrichmentError = e instanceof Error ? e.message : 'Failed to load auto-generated data';
		} finally {
			enrichmentLoading = false;
		}
	}

	// Serves "nothing generated yet," "stale" (ctranslate2_stale), and "user
	// wants a manual redo" alike - see generate_fallback_word_enrichment's
	// docstring, router.py, for why this is one endpoint/one function
	// regardless of which of those three is actually true when it's called.
	async function generateFallback() {
		enrichmentGenerating = true;
		enrichmentError = '';
		try {
			enrichment = await api.generateFallbackEnrichment(word) as WordEnrichment;
		} catch (e: unknown) {
			enrichmentError = e instanceof Error ? e.message : 'Failed to generate';
		} finally {
			enrichmentGenerating = false;
		}
	}

	// Copies the already-displayed Auto-generated values into the new-entry
	// draft, for the "quick definition when creating a new UserWord" use
	// case from this feature's own planning conversation - reuses whatever
	// the Auto-generated section already fetched/generated rather than a
	// separate code path, so there's exactly one place that calls the
	// generation endpoints.
	function fillFromEnrichment() {
		if (enrichment?.pinyin) uwNewDraft.pronunciation = enrichment.pinyin;
		if (enrichment?.translation) uwNewDraft.meaning = enrichment.translation;
	}

	// Re-fetch whenever the word this panel is showing changes - the parent
	// keeps the same component instance mounted across word selections
	// (only `word`/`context` change), rather than remounting per word.
	$effect(() => {
		word;
		load();
		loadEnrichment();
	});

	// Persists the in-progress UserWord/Note/sample-sentence drafts for this
	// word to sessionStorage as they change (see wordDraftPersistence.ts's
	// docstring for why - recovering from a mobile browser discarding/
	// reloading this page mid-edit) - load()'s restoration above is the
	// other half. Cleared automatically once nothing is actually in
	// progress (every add/edit mode closed, no unsaved sentence text), so
	// this never lingers after a normal Save or Cancel - both already reset
	// the fields this checks.
	$effect(() => {
		const isEmpty = !newSentenceDraft.trim() && !editingNote
			&& !uwAddingGlobal && !uwAddingText && !uwAddingAnalysis && uwEditingIds.size === 0;
		if (isEmpty) {
			clearWordDraft(word);
			return;
		}
		saveWordDraft(word, {
			newSentenceDraft,
			editingNote, noteDraft,
			uwAddingGlobal, uwAddingText, uwAddingAnalysis, uwNewDraft: { ...uwNewDraft },
			uwEditingIds: [...uwEditingIds],
			uwDrafts: Object.fromEntries([...uwEditingIds].map((id) => [id, uwDrafts[id]])),
		});
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
			const wasGarbage = detail?.is_garbage ?? false;
			if (wasGarbage) {
				await api.unmarkGarbageWord(word);
			} else {
				await api.createGarbageWord(word);
			}
			if (detail) detail = { ...detail, is_garbage: !detail.is_garbage };
			if (!wasGarbage) onGarbageMarked?.();
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
			const fields: { pronunciation: string | null; meaning: string | null; notes: string | null; affects_dag?: AffectsDag | null } = {
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
		uwNewDraft = { pronunciation: '', meaning: '', notes: '', affectsDag: 'increase' };
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
			const fields: { pronunciation: string | null; meaning: string | null; notes: string | null; affects_dag?: AffectsDag | null } = {
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

	// Empty/whitespace-only text deletes the note server-side rather than
	// persisting empty text (see upsert_word_note's docstring, router.py) -
	// mirrored here so the panel's own local state matches what the server
	// actually did without needing to read the response body.
	async function saveNote() {
		const trimmed = noteDraft.trim();
		savingNote = true;
		try {
			await api.upsertWordNote(word, trimmed);
			const nextNote = trimmed || null;
			if (detail) detail = { ...detail, note: nextNote };
			onNoteChanged?.(nextNote);
			editingNote = false;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to save note';
		} finally {
			savingNote = false;
		}
	}

	async function removeNote() {
		savingNote = true;
		try {
			await api.deleteWordNote(word);
			if (detail) detail = { ...detail, note: null };
			onNoteChanged?.(null);
			editingNote = false;
			noteDraft = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove note';
		} finally {
			savingNote = false;
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
<div class="w-full lg:w-72 max-h-[85vh] overflow-y-auto bg-white dark:bg-slate-900 rounded-t-2xl lg:rounded-lg shadow-sm p-4">
	{#if loading}
		<p class="text-gray-500 dark:text-slate-400 text-sm">Loading...</p>
	{:else if error && !detail}
		<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-3 py-2 rounded text-sm mb-2">{error}</div>
		<button onclick={onClose} class="text-sm text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Close</button>
	{:else if detail}
		<div class="flex justify-between items-start mb-3">
			<h2 class="text-3xl font-medium">{detail.word}</h2>
			<button onclick={onClose} class="text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300">✕</button>
		</div>

		{#if error}
			<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-3 py-2 rounded text-sm mb-3">{error}</div>
		{/if}

		<!-- Familiarity + quick actions - always global, always fully
		     editable regardless of context (see KnownWord/StarredWord's
		     docstrings, models.py). -->
		<div class="border-b border-gray-100 dark:border-slate-800 mb-4 pb-4">
			<div class="mb-2">
				<!-- Same shared dot widget the results table/Known Words page
				     already use, rather than this panel's own bespoke
				     numbered-square grid - see analyze/[id]/+page.svelte's mobile
				     card list for the same swap, done for the same reason (one
				     less duplicate familiarity-editing UI to keep visually in
				     sync). Sized larger (w-5 h-5) than the table's compact w-2
				     h-2 dots - this is the one dedicated familiarity-editing
				     surface in the panel, not a dense table column. -->
				<FamiliarityDots
					familiarity={detail.familiarity}
					disabled={updatingFamiliarity}
					dotSize="w-5 h-5"
					onSetFamiliarity={setFamiliarity}
				/>
			</div>
			<div class="flex flex-wrap items-center gap-0.5">
				<button
					onclick={toggleGlobalUserWord}
					disabled={togglingGlobalUserWord}
					class="p-1.5 rounded {globalUserWord ? 'text-emerald-600' : 'text-gray-400 dark:text-slate-500'} hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-500/10 disabled:opacity-50"
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
					class="p-1.5 rounded {detail.is_starred ? 'text-amber-500' : 'text-gray-400 dark:text-slate-500'} hover:text-amber-500 hover:bg-amber-50 disabled:opacity-50"
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
					class="p-1.5 rounded {detail.is_garbage ? 'text-red-600 dark:text-red-400' : 'text-gray-400 dark:text-slate-500'} hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 disabled:opacity-50"
					title={detail.is_garbage ? 'Marked as garbage — click to unmark' : 'Mark as garbage'}
					aria-label="Garbage"
				>
					<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="10" cy="10" r="7.25" />
						<path d="M5.15 14.85l9.7-9.7" />
					</svg>
				</button>
			</div>
		</div>

		<!-- Corpus frequency -->
		<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">Corpus frequency</p>
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
			<p class="text-sm text-gray-400 dark:text-slate-500">No frequency data for this word.</p>
		{/if}

		<!-- HSK -->
		<div class="border-t border-gray-100 dark:border-slate-800 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">HSK</p>

			{#if detail.hsk_v2_2012 || detail.hsk_v3_2021 || detail.hsk_v3_2026 || detail.forms.length > 0}
				<div class="flex flex-wrap gap-1 mb-3">
					{#if detail.hsk_v2_2012}
						<span class="text-xs px-2 py-1 bg-blue-100 dark:bg-blue-500/15 text-blue-700 dark:text-blue-400 rounded-full">HSK 2012: {detail.hsk_v2_2012}</span>
					{/if}
					{#if detail.hsk_v3_2021}
						<span class="text-xs px-2 py-1 bg-purple-100 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300 rounded-full">HSK 2021: {detail.hsk_v3_2021}</span>
					{/if}
					{#if detail.hsk_v3_2026}
						<span class="text-xs px-2 py-1 bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300 rounded-full">HSK 2026: {detail.hsk_v3_2026}</span>
					{/if}
				</div>

				{#if detail.forms.length > 0}
					<div class="space-y-3">
						{#each detail.forms as form, i}
							<div class="{i > 0 ? 'border-t border-gray-100 dark:border-slate-800 pt-3' : ''}">
								{#if detail.forms.length > 1}
									<p class="text-xs text-gray-400 dark:text-slate-500 mb-1">Form {i + 1}</p>
								{/if}
								{#if form.traditional && form.traditional !== detail.word}
									<p class="text-sm text-gray-600 dark:text-slate-400 mb-1">
										Traditional: <span class="font-medium">{form.traditional}</span>
									</p>
								{/if}
								{#if form.pinyin}
									<p class="text-sm text-blue-600 dark:text-blue-400 mb-1">{form.pinyin}</p>
								{/if}
								{#if form.meanings.length > 0}
									<ul class="text-sm text-gray-700 dark:text-slate-300 space-y-0.5">
										{#each form.meanings as meaning}
											<li>• {meaning}</li>
										{/each}
									</ul>
								{/if}
								{#if form.classifiers.length > 0}
									<p class="text-xs text-gray-500 dark:text-slate-400 mt-1">Classifiers: {form.classifiers.join(', ')}</p>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			{:else}
				<p class="text-sm text-gray-400 dark:text-slate-500">No HSK entry for this word.</p>
			{/if}
		</div>

		<!-- CC-CEDICT -->
		<div class="border-t border-gray-100 dark:border-slate-800 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">CC-CEDICT</p>

			{#if detail.cedict.length > 0}
				<div class="space-y-3">
					{#each detail.cedict as sense, i}
						<div class="{i > 0 ? 'border-t border-gray-100 dark:border-slate-800 pt-3' : ''}">
							{#if detail.cedict.length > 1}
								<p class="text-xs text-gray-400 dark:text-slate-500 mb-1">Sense {i + 1}</p>
							{/if}
							{#if sense.traditional && sense.traditional !== detail.word}
								<p class="text-sm text-gray-600 dark:text-slate-400 mb-1">
									Traditional: <span class="font-medium">{sense.traditional}</span>
								</p>
							{/if}
							{#if sense.pinyin}
								<p class="text-sm text-blue-600 dark:text-blue-400 mb-1">{sense.pinyin}</p>
							{/if}
							{#if sense.definitions.length > 0}
								<ul class="text-sm text-gray-700 dark:text-slate-300 space-y-0.5">
									{#each sense.definitions as definition}
										<li>• {definition}</li>
									{/each}
								</ul>
							{/if}
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-sm text-gray-400 dark:text-slate-500">No CC-CEDICT entry for this word.</p>
			{/if}
		</div>

		<!-- Auto-generated - only offered when there's an actual gap to fill
		     (no CEDICT sense, no HSK form - both of those already carry their
		     own pinyin/meaning). Third source in this panel's Pleco-style
		     "each source under its own heading" layout, not a special case -
		     see WordEnrichment's docstring (models.py, backend) for the full
		     design and why this is shared across every user. -->
		{#if detail.cedict.length === 0 && detail.forms.length === 0}
			<div class="border-t border-gray-100 dark:border-slate-800 mt-4 pt-3">
				<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">Auto-generated</p>

				{#if enrichmentError}
					<p class="text-sm text-red-600 dark:text-red-400 mb-2">{enrichmentError}</p>
				{/if}

				{#if enrichmentLoading}
					<p class="text-sm text-gray-400 dark:text-slate-500">Loading...</p>
				{:else if enrichment?.pinyin || enrichment?.translation}
					<div class="space-y-1 mb-2">
						{#if enrichment.pinyin}
							<p class="text-sm text-blue-600 dark:text-blue-400">{enrichment.pinyin}</p>
						{/if}
						{#if enrichment.translation}
							<p class="text-sm text-gray-700 dark:text-slate-300">
								{enrichment.translation}
								<span class="text-xs text-gray-400 dark:text-slate-500">
									— {enrichment.google_translation ? 'Google Translate' : 'local model'}
								</span>
							</p>
						{/if}
					</div>
					{#if enrichment.ctranslate2_stale && !enrichment.google_translation}
						<p class="text-xs text-amber-600 mb-2">
							This was generated with an older local model - the translation may be out of date.
						</p>
					{/if}
					<button
						onclick={generateFallback}
						disabled={enrichmentGenerating}
						class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 disabled:opacity-50"
					>
						{enrichmentGenerating ? 'Regenerating...' : enrichment.ctranslate2_stale ? 'Refresh' : 'Regenerate'}
					</button>
				{:else}
					<p class="text-sm text-gray-400 dark:text-slate-500 mb-2">
						No dictionary entry for this word - pinyin and a rough translation can be generated
						from a local model instead.
					</p>
					<button
						onclick={generateFallback}
						disabled={enrichmentGenerating}
						class="text-sm px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
					>
						{enrichmentGenerating ? 'Generating...' : 'Generate'}
					</button>
				{/if}
			</div>
		{/if}

		<!-- Your entries (UserWord) -->
		<div class="border-t border-gray-100 dark:border-slate-800 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">Your entries</p>

			{#snippet uwFields(draftKey: string, draft: { pronunciation: string; meaning: string; notes: string; affectsDag: AffectsDag | null }, showAffectsDag: boolean, idPrefix: string)}
				<div class="space-y-2">
					<div>
						<label for="{idPrefix}-pron" class="text-xs text-gray-500 dark:text-slate-400">Pronunciation</label>
						<input id="{idPrefix}-pron" type="text" bind:value={draft.pronunciation} placeholder="e.g. dà yě láng" class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5" />
					</div>
					<div>
						<label for="{idPrefix}-meaning" class="text-xs text-gray-500 dark:text-slate-400">
							Meaning / definition
							<span class="text-gray-400 dark:text-slate-500 font-normal">- separate senses with "/", CC-CEDICT style</span>
						</label>
						<textarea id="{idPrefix}-meaning" bind:value={draft.meaning} placeholder="to run/to flee/(of a horse) to gallop" rows="2" class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"></textarea>
					</div>
					<div>
						<label for="{idPrefix}-notes" class="text-xs text-gray-500 dark:text-slate-400">Notes</label>
						<textarea id="{idPrefix}-notes" bind:value={draft.notes} placeholder="Any other notes — context, mnemonics, etc." rows="2" class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"></textarea>
					</div>
					{#if showAffectsDag}
						<!-- 4-way radio, not a checkbox - NULL ("no preference") is a
						     real, distinct value from 'neutral' ("no opinion, but
						     don't inherit"), which is itself distinct from
						     'increase'/'decrease' - see UserWord.affects_dag's
						     docstring (models.py) for the full 3-state design.
						     Hidden for an analysis-scoped entry - it can never have
						     an observable effect there. -->
						<div class="text-xs text-gray-500 dark:text-slate-400">
							<span class="block mb-1">Segmentation weight</span>
							<label class="flex items-center gap-1.5 mb-0.5">
								<input type="radio" name="{idPrefix}-affects-dag" checked={draft.affectsDag === 'increase'} onchange={() => draft.affectsDag = 'increase'} />
								Increase - reliably wins over alternatives
							</label>
							<label class="flex items-center gap-1.5 mb-0.5">
								<input type="radio" name="{idPrefix}-affects-dag" checked={draft.affectsDag === 'neutral'} onchange={() => draft.affectsDag = 'neutral'} />
								Neutral - competes on its own corpus frequency only
							</label>
							<label class="flex items-center gap-1.5 mb-0.5">
								<input type="radio" name="{idPrefix}-affects-dag" checked={draft.affectsDag === 'decrease'} onchange={() => draft.affectsDag = 'decrease'} />
								Decrease - suppressed below any real alternative
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
				<div class="mb-2 pb-2 border-b border-gray-50 dark:border-slate-800 last:border-0">
					<div class="flex justify-between items-center mb-1 gap-2">
						<span class="text-xs font-medium text-gray-500 dark:text-slate-400 truncate">{entryLabel(entry)}</span>
						{#if editable}
							<div class="flex gap-2 shrink-0">
								{#if !editing}
									<button onclick={() => startEditingUserWord(entry)} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300">Edit</button>
								{/if}
								<button onclick={() => deleteUserWordEntry(entry)} disabled={uwSavingId === entry.id} class="text-xs text-red-400 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50">Delete</button>
							</div>
						{:else if link}
							<a href={link} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 shrink-0">View →</a>
						{/if}
					</div>

					{#if editing}
						{@render uwFields(`entry-${entry.id}`, uwDrafts[entry.id], entry.scope !== 'analysis', `uw-${entry.id}`)}
						<div class="flex gap-2 pt-1">
							<button onclick={() => saveUserWordEntry(entry)} disabled={uwSavingId === entry.id} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
								{uwSavingId === entry.id ? 'Saving...' : 'Save'}
							</button>
							<button onclick={() => cancelEditingUserWord(entry.id)} disabled={uwSavingId === entry.id} class="text-xs px-3 py-1.5 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
						</div>
					{:else}
						<div class="space-y-1">
							{#if entry.pronunciation}<p class="text-sm text-blue-600 dark:text-blue-400 break-words">{entry.pronunciation}</p>{/if}
							{#if entry.meaning}<p class="text-sm text-gray-700 dark:text-slate-300 break-words">{entry.meaning}</p>{/if}
							{#if entry.notes}<p class="text-xs text-gray-500 dark:text-slate-400 italic break-words">{entry.notes}</p>{/if}
							{#if !entry.pronunciation && !entry.meaning && !entry.notes}<p class="text-sm text-gray-400 dark:text-slate-500">No details added yet.</p>{/if}
							{#if entry.scope !== 'analysis' && entry.affects_dag === 'decrease'}
								<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-600 dark:bg-red-500/15 dark:text-red-300">Decreased segmentation weight</span>
							{:else if entry.scope !== 'analysis' && entry.affects_dag === 'neutral'}
								<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-400">Neutral segmentation weight</span>
							{:else if entry.scope !== 'analysis' && entry.affects_dag === null}
								<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-400 dark:bg-slate-500/15 dark:text-slate-500">No segmentation preference (inherits)</span>
							{/if}
							{#if !editable}
								<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 dark:bg-slate-500/15 dark:text-slate-400">Read-only from here</span>
							{/if}
						</div>
					{/if}
				</div>
			{/snippet}

			<!-- Global - always shown, always editable. -->
			{#if globalUserWord}
				{@render uwEntryCard(globalUserWord)}
			{:else if uwAddingGlobal}
				<div class="mb-2 pb-2 border-b border-gray-50 dark:border-slate-800">
					<span class="text-xs font-medium text-gray-500 dark:text-slate-400">Global</span>
					{#if enrichment?.pinyin || enrichment?.translation}
						<button onclick={fillFromEnrichment} class="block text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 mb-1.5">
							Fill from auto-generated ({enrichment.pinyin}{enrichment.pinyin && enrichment.translation ? ' — ' : ''}{enrichment.translation})
						</button>
					{/if}
					{@render uwFields('new-global', uwNewDraft, true, 'uw-new-global')}
					<div class="flex gap-2 pt-1">
						<button onclick={() => saveNewUserWord('global')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
							{uwSavingId === -1 ? 'Saving...' : 'Save'}
						</button>
						<button onclick={() => cancelAddingUserWord('global')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
					</div>
				</div>
			{:else}
				<button onclick={() => startAddingUserWord('global')} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 mb-2">+ Add global entry</button>
			{/if}

			<!-- Text-specific -->
			{#if textUserWords.length > 0}
				<button onclick={() => uwTextExpanded = !uwTextExpanded} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300 flex items-center gap-1 mt-1">
					<span class="transition-transform {uwTextExpanded ? 'rotate-90' : ''}">▸</span>
					Text-specific ({textUserWords.length})
				</button>
				{#if uwTextExpanded}
					<div class="mt-1 pl-2 border-l-2 border-gray-100 dark:border-slate-800">
						{#each textUserWords as entry (entry.id)}
							{@render uwEntryCard(entry)}
						{/each}
					</div>
				{/if}
			{/if}
			{#if context.type !== 'global' && !currentTextUserWord}
				{#if uwAddingText}
					<div class="mb-2 pb-2 border-b border-gray-50 dark:border-slate-800 mt-1">
						<span class="text-xs font-medium text-gray-500 dark:text-slate-400">{context.textTitle ?? 'This text'}</span>
						{@render uwFields('new-text', uwNewDraft, true, 'uw-new-text')}
						<div class="flex gap-2 pt-1">
							<button onclick={() => saveNewUserWord('text')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
								{uwSavingId === -1 ? 'Saving...' : 'Save'}
							</button>
							<button onclick={() => cancelAddingUserWord('text')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
						</div>
					</div>
				{:else}
					<button onclick={() => startAddingUserWord('text')} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 mt-1 block">+ Add entry for this text</button>
				{/if}
			{/if}

			<!-- Analysis-specific -->
			{#if analysisUserWords.length > 0}
				<button onclick={() => uwAnalysisExpanded = !uwAnalysisExpanded} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300 flex items-center gap-1 mt-2">
					<span class="transition-transform {uwAnalysisExpanded ? 'rotate-90' : ''}">▸</span>
					Analysis-specific ({analysisUserWords.length})
				</button>
				{#if uwAnalysisExpanded}
					<div class="mt-1 pl-2 border-l-2 border-gray-100 dark:border-slate-800">
						{#each analysisUserWords as entry (entry.id)}
							{@render uwEntryCard(entry)}
						{/each}
					</div>
				{/if}
			{/if}
			{#if context.type === 'analysis' && !currentAnalysisUserWord}
				{#if uwAddingAnalysis}
					<div class="mb-2 pb-2 border-b border-gray-50 dark:border-slate-800 mt-1">
						<span class="text-xs font-medium text-gray-500 dark:text-slate-400">This analysis</span>
						{@render uwFields('new-analysis', uwNewDraft, false, 'uw-new-analysis')}
						<div class="flex gap-2 pt-1">
							<button onclick={() => saveNewUserWord('analysis')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
								{uwSavingId === -1 ? 'Saving...' : 'Save'}
							</button>
							<button onclick={() => cancelAddingUserWord('analysis')} disabled={uwSavingId === -1} class="text-xs px-3 py-1.5 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
						</div>
					</div>
				{:else}
					<button onclick={() => startAddingUserWord('analysis')} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 mt-2 block">+ Add entry for this analysis</button>
				{/if}
			{/if}
		</div>

		<!-- Sample sentences - independent of Your entries above (see
		     SampleSentence's docstring, models.py) - global per user+word,
		     no scoping, so unaffected by this change. -->
		<div class="border-t border-gray-100 dark:border-slate-800 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">Sample sentences</p>

			{#if detail.sample_sentences.length}
				<ul class="space-y-1.5 mb-2">
					{#each detail.sample_sentences as s (s.id)}
						<li class="flex items-start justify-between gap-2">
							<p class="text-sm text-gray-700 dark:text-slate-300 min-w-0 break-words">{s.sentence}</p>
							<button onclick={() => removeSampleSentence(s.id)} disabled={deletingSentenceId === s.id} class="text-gray-300 dark:text-slate-600 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50 shrink-0" title="Remove sample sentence" aria-label="Remove sample sentence">✕</button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="text-sm text-gray-400 dark:text-slate-500 mb-2">No sample sentences yet.</p>
			{/if}

			<div class="flex gap-1">
				<input
					type="text"
					bind:value={newSentenceDraft}
					placeholder="Paste an example sentence..."
					class="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
					onkeydown={(e) => { if (e.key === 'Enter') addSampleSentence(); }}
				/>
				<button onclick={addSampleSentence} disabled={!newSentenceDraft.trim() || savingSentence} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50 shrink-0">
					{savingSentence ? '...' : 'Add'}
				</button>
			</div>
		</div>

		<!-- Note - a single free-text note per word, independent of starred/
		     known/user-word status (see WordNote's docstring, models.py).
		     Originally a StarredWord-only field ("+ Note" on the Starred
		     Words profile page); generalized here so any word can have one. -->
		<div class="border-t border-gray-100 dark:border-slate-800 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">Note</p>

			{#if editingNote}
				<div class="flex flex-col gap-1.5">
					<textarea
						bind:value={noteDraft}
						rows="3"
						placeholder="Add a note..."
						class="border border-gray-300 rounded px-2 py-1 text-sm resize-none"
					></textarea>
					<div class="flex items-center gap-2">
						<button onclick={saveNote} disabled={savingNote} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
							{savingNote ? 'Saving...' : 'Save'}
						</button>
						<button onclick={() => { editingNote = false; noteDraft = detail?.note ?? ''; }} disabled={savingNote} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
						{#if detail.note}
							<button onclick={removeNote} disabled={savingNote} class="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-400 ml-auto">Delete</button>
						{/if}
					</div>
				</div>
			{:else if detail.note}
				<p class="text-sm text-gray-700 dark:text-slate-300 whitespace-pre-wrap break-words mb-1.5">{detail.note}</p>
				<button onclick={() => { editingNote = true; noteDraft = detail?.note ?? ''; }} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300">Edit note</button>
			{:else}
				<button onclick={() => { editingNote = true; noteDraft = ''; }} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300">+ Add note</button>
			{/if}
		</div>

		<!-- Visibility ("hide from results") - same layout pattern as Your
		     entries above, but ALL three scopes (including analysis) are
		     meaningfully editable here - an analysis-scoped hidden override
		     has a real effect every time that exact analysis is reopened,
		     unlike an analysis-scoped affects_dag (see UserWord's docstring,
		     models.py). Placed last, not grouped with the dictionary-ish
		     sections above. -->
		<div class="border-t border-gray-100 dark:border-slate-800 mt-4 pt-3">
			<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide mb-2">Visibility</p>

			{#snippet visEntryRow(entry: VisibilityEntry)}
				{@const editable = isEntryEditable(entry, context)}
				{@const link = jumpLink(entry)}
				<div class="flex items-center justify-between gap-2 py-1">
					<span class="text-xs text-gray-500 dark:text-slate-400 truncate">{entryLabel(entry)}</span>
					{#if editable}
						<div class="flex items-center gap-2 shrink-0">
							<button
								onclick={() => setVisibility(entry, !entry.hidden)}
								disabled={visSavingId === entry.id}
								class="text-xs px-2 py-1 rounded-full disabled:opacity-50 {entry.hidden ? 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300' : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'}"
							>
								{entry.hidden ? 'Hidden' : 'Shown'}
							</button>
							<button onclick={() => removeVisibilityEntry(entry)} disabled={visSavingId === entry.id} class="text-xs text-red-400 hover:text-red-600 dark:text-red-500 dark:hover:text-red-400 disabled:opacity-50">
								Remove
							</button>
						</div>
					{:else}
						<div class="flex items-center gap-2 shrink-0">
							<span class="text-xs px-2 py-1 rounded-full {entry.hidden ? 'bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-400' : 'bg-gray-100 text-gray-500 dark:bg-slate-500/15 dark:text-slate-400'}">
								{entry.hidden ? 'Hidden' : 'Shown'}
							</span>
							{#if link}<a href={link} class="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300">View →</a>{/if}
						</div>
					{/if}
				</div>
			{/snippet}

			{#snippet visAddRow(scope: 'global' | 'text' | 'analysis', label: string, adding: boolean, setAdding: (v: boolean) => void, newKey: 'new-global' | 'new-text' | 'new-analysis')}
				<div class="flex items-center justify-between gap-2 py-1">
					<span class="text-xs text-gray-500 dark:text-slate-400 truncate">{label}</span>
					{#if adding}
						<div class="flex items-center gap-1 shrink-0">
							<button onclick={() => setVisibility(newKey, false)} disabled={visSavingId === -1} class="text-xs px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 hover:bg-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:hover:bg-emerald-500/25 disabled:opacity-50">Shown</button>
							<button onclick={() => setVisibility(newKey, true)} disabled={visSavingId === -1} class="text-xs px-2 py-1 rounded-full bg-slate-200 text-slate-700 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600 disabled:opacity-50">Hidden</button>
							<button onclick={() => setAdding(false)} class="text-xs text-gray-400 hover:text-gray-600 dark:text-slate-500 dark:hover:text-slate-300">Cancel</button>
						</div>
					{:else}
						<div class="flex items-center gap-2 shrink-0">
							<span class="text-xs text-gray-400 dark:text-slate-500">Not set - inherits</span>
							<button onclick={() => setAdding(true)} class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300">+ Override</button>
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
				<button onclick={() => visTextExpanded = !visTextExpanded} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300 flex items-center gap-1 mt-1">
					<span class="transition-transform {visTextExpanded ? 'rotate-90' : ''}">▸</span>
					Text-specific ({textVisibility.length})
				</button>
				{#if visTextExpanded}
					<div class="mt-1 pl-2 border-l-2 border-gray-100 dark:border-slate-800">
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
				<button onclick={() => visAnalysisExpanded = !visAnalysisExpanded} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300 flex items-center gap-1 mt-2">
					<span class="transition-transform {visAnalysisExpanded ? 'rotate-90' : ''}">▸</span>
					Analysis-specific ({analysisVisibility.length})
				</button>
				{#if visAnalysisExpanded}
					<div class="mt-1 pl-2 border-l-2 border-gray-100 dark:border-slate-800">
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
