<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import type { Scope } from '$lib/api';
	import { goto } from '$app/navigation';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();

	// Filter preferences persist across reloads as a global per-browser
	// setting (not per-analysis) - "always resets to hide >= 4" was the
	// complaint being fixed. Search text itself is deliberately NOT
	// persisted - a stale search term left over from a previous analysis
	// would just be confusing on a new one.
	const FILTER_STORAGE_KEY = 'mandarin_tools_analysis_filters';

	// Per-bucket hide/iso state, keyed by bucket id (see BUCKETS below).
	interface BucketFilterState {
		hide: boolean;
		iso: boolean;
	}

	interface StoredFilters {
		buckets: Record<string, BucketFilterState>;
		minFamiliarityFilter: number;
		searchScope: 'filtered' | 'all';
		// See SortColumn's declaration further down - referencing it here is
		// fine, TS type positions aren't subject to the declaration-order
		// rules runtime `let`/`const` bindings are.
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

	interface WordResult {
		word: string;
		count: number;
		source: string;
		familiarity: number | null;
		is_garbage: boolean;
		// Resolved (never persisted) same as is_garbage - see
		// WordVisibility's docstring (models.py). hidden_governing_scope is
		// "global"/"text"/"analysis", or "default" if no override applies
		// anywhere (is_hidden is then always false).
		is_hidden: boolean;
		hidden_governing_scope: string;
		// Resolved (never persisted), same pattern as is_garbage/is_hidden -
		// whether this word has an applicable UserWord row anywhere relevant
		// to this viewing context (see backend's _resolve_user_word_presence,
		// router.py). Distinct from the `userWords` Set below, which is
		// global-only (drives the results-table "+ Add word" button
		// specifically) - this field reflects the full analysis/text/global
		// resolution, used by the "User words" filter bucket.
		is_user_word: boolean;
	}

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

	interface UserWordDetail {
		id: number;
		pronunciation: string | null;
		meaning: string | null;
		notes: string | null;
		// Whether this entry's frequency boosts DAG segmentation - tri-state
		// (see UserWord's docstring, models.py): null means "no opinion at
		// this scope, inherit from the next broader scope," NOT the same as
		// false. Only meaningful at global/text scope; an analysis-scoped
		// entry's value here can never have an observable effect (see
		// build_user_overlay, segmenter_loader.py), so the UI never shows a
		// control for it.
		affects_dag: boolean | null;
		scope_analysis_id: number | null;
		scope_input_text_id: number | null;
	}

	interface WordVisibilityEntry {
		id: number;
		word: string;
		hidden: boolean;
		scope_analysis_id: number | null;
		scope_input_text_id: number | null;
	}

	interface WordDetail {
		word: string;
		frequency: number | null;
		hsk_v2_2012: number | null;
		hsk_v3_2021: number | null;
		hsk_v3_2026: number | null;
		forms: HskForm[];
		cedict: CedictSense[];
		// Every UserWord entry across the relevant scope levels, most
		// specific first - never resolved to one, see backend's WordDetail
		// docstring (schemas.py).
		user_words: UserWordDetail[];
		// Same multi-entry, most-specific-first shape as user_words, for the
		// Visibility section - see WordVisibility's docstring (models.py).
		word_visibility: WordVisibilityEntry[];
		sample_sentences: SampleSentence[];
	}

	interface Analysis {
		analysis_id: number;
		input_text_id: number;
		title: string | null;
		total_words: number;
		unique_words: number;
		results: WordResult[];
	}

	interface WordOccurrence {
		start: number;
		end: number;
		before: string;
		match: string;
		after: string;
	}

	let analysis: Analysis | null = $state(null);
	let loading = $state(true);
	let error = $state('');
	let updatingWord = $state('');
	let garbageWords = $state(new Set<string>());
	let togglingGarbage = $state('');
	let knownWords = $state<Record<string, number | null>>({});
	let userWords = $state(new Set<string>());
	// affects_dag of each word's GLOBAL UserWord entry specifically (mirrors
	// how `userWords` itself is global-only - see its own comment in
	// onMount) - lets the results-table quick-add button distinguish "in
	// your dictionary, boosts segmentation" from "in your dictionary,
	// excluded from segmentation" with a color difference, without a
	// per-row fetch.
	let userWordAffectsDag: Record<string, boolean | null> = $state({});
	let addingUserWord = $state('');
	let starredWords = $state(new Set<string>());
	let togglingStarred = $state('');
	// Visibility ("hide from results") - visibilityRowsByWord caches the up
	// -to-3 raw WordVisibility rows per word, fetched lazily the first time
	// that word's quick-action menu is opened (same lazy+cache pattern as
	// contextByWord below), used to build the menu (see buildVisibilityMenu)
	// and kept in sync with the panel's own selectedWord.word_visibility
	// when either mutates.
	let visibilityRowsByWord: Record<string, WordVisibilityEntry[]> = $state({});
	let loadingVisibilityFor = $state(new Set<string>());
	let visibilityMenuOpenFor: string | null = $state(null);
	let togglingVisibilityAction: string | null = $state(null);
	// Panel's own Visibility section - which scope's request is in flight,
	// and which scope's "+ Override" is currently expanded to show its
	// Shown/Hidden choice.
	let togglingVisibilityScope: Scope | null = $state(null);
	let addingVisibilityOverrideFor: Scope | null = $state(null);
	// Mobile card list only - independent per-row accordion toggles (see
	// snippets iconPlusMinus/iconHamburger and the sm:hidden card block).
	let expandedInfo = $state(new Set<string>());
	let expandedActions = $state(new Set<string>());
	let selectedWord: WordDetail | null = $state(null);
	let loadingDetail = $state(false);
	// Where a NEW user-word entry from the panel should land ("+ Add entry"
	// picks among whichever scopes don't already have one) - forward-looking,
	// reset to "global" each time a different word's panel opens. Familiarity
	// has no scope of its own, it's always global (see KnownWord's docstring,
	// models.py).
	let userWordScope: Scope = $state('global');
	// Context (word-in-source-text) is keyed by word rather than tied to the
	// panel, since it now lives at the row/card level and multiple rows can
	// have their context expanded independently at once (desktop chevrons,
	// mobile's existing "+" accordion). Fetched lazily and cached per word.
	let expandedContext = $state(new Set<string>());
	let contextByWord: Record<string, WordOccurrence[]> = $state({});
	let loadingContextFor = $state(new Set<string>());
	let minFamiliarityFilter = $state(storedFilters.minFamiliarityFilter ?? 4);
	let searchQuery = $state('');
	let searchScope: 'filtered' | 'all' = $state(storedFilters.searchScope ?? 'filtered');
	let newSentenceDraft = $state('');
	let savingSentence = $state(false);
	let deletingSentenceId: number | null = $state(null);

	// UserWord "Your entries" list - each entry is independently editable,
	// keyed by its own row id (real ids are always positive). affectsDag is
	// tri-state (true/false/null - see UserWord.affects_dag's docstring,
	// models.py) and only ever read/sent for non-analysis-scoped entries -
	// an analysis-scoped value can never have an observable effect.
	let entryEditingIds: Set<number> = $state(new Set());
	let entryDrafts: Record<number, { pronunciation: string; meaning: string; notes: string; affectsDag: boolean | null }> = $state({});
	let savingEntryId: number | null = $state(null);
	// "+ Add entry" (for a scope with no entry yet) is structurally
	// different from editing an existing one - it doesn't have a row id yet.
	// Defaults affectsDag to true (not null) - a deliberate "+ Add entry"
	// action is a reasonable place to default to "yes, boost segmentation,"
	// unlike a bare request that only sets other fields (see
	// UserWordCreate/UserWordUpsert, schemas.py) - "no preference" is still
	// pickable via the tri-state control below.
	let addingNewEntry = $state(false);
	let newEntryDraft = $state<{ pronunciation: string; meaning: string; notes: string; affectsDag: boolean | null }>({ pronunciation: '', meaning: '', notes: '', affectsDag: true });

	const id = $derived(parseInt(params.id));

	function containsChinese(word: string): boolean {
		return /[\u4e00-\u9fff]/.test(word);
	}

	// --- Filter bucket registry -------------------------------------------
	// One array of bucket definitions, not scattered booleans - this is what
	// the chip bar renders from and what future buckets get added to. Each
	// bucket's `test` is a plain closure, so buckets backed by component
	// state (starred, non-Chinese) stay reactive without needing their own
	// $derived - they just read the live outer binding when called.
	//
	// `defaultHide` - Garbage, Hidden, and Non-Chinese default to hide=true
	// (matches the pre-rework defaults for all three); every other bucket
	// starts fully unfiltered by default.
	interface Bucket {
		id: string;
		label: string;
		iconKey: string;
		test: (r: WordResult) => boolean;
		defaultHide: boolean;
	}

	const BUCKETS: Bucket[] = [
		{ id: 'garbage', label: 'Garbage', iconKey: 'garbage', test: (r) => r.is_garbage, defaultHide: true },
		{ id: 'hidden', label: 'Hidden', iconKey: 'hidden', test: (r) => r.is_hidden, defaultHide: true },
		{ id: 'userWord', label: 'User words', iconKey: 'userWord', test: (r) => r.is_user_word, defaultHide: false },
		{ id: 'extraMatch', label: 'Extra matches', iconKey: 'extraMatch', test: (r) => r.source === 'longest_match_only', defaultHide: false },
		{ id: 'unrecognized', label: 'Unrecognized sequences', iconKey: 'unrecognized', test: (r) => r.source === 'token', defaultHide: false },
		{ id: 'unknown', label: 'Unknown', iconKey: 'unknown', test: (r) => r.source === 'unknown', defaultHide: false },
		// 'trie' kept for legacy rows - see AnalysisResult.source's CHECK
		// constraint comment (models.py).
		{ id: 'dag', label: 'DAG words', iconKey: 'dag', test: (r) => r.source === 'dag' || r.source === 'trie', defaultHide: false },
		// Starred has no resolved WordResult field (unlike garbage/hidden/
		// user-word) - it's the same separately-fetched `starredWords` Set
		// the row/card quick-actions already use, so this stays live via
		// closure rather than needing a backend round trip of its own.
		{ id: 'starred', label: 'Starred', iconKey: 'starred', test: (r) => starredWords.has(r.word), defaultHide: false },
		{ id: 'nonChinese', label: 'Non-Chinese', iconKey: 'nonChinese', test: (r) => !containsChinese(r.word), defaultHide: true },
	];

	let bucketState: Record<string, BucketFilterState> = $state(
		Object.fromEntries(BUCKETS.map((b) => [b.id, {
			hide: storedFilters.buckets?.[b.id]?.hide ?? b.defaultHide,
			iso: storedFilters.buckets?.[b.id]?.iso ?? false,
		}]))
	);

	// Chip bar - only one bucket's popover open at a time. hide/iso changes
	// apply live (no separate apply button), same as the old checkboxes did.
	let openBucketPopoverFor: string | null = $state(null);

	function toggleBucketPopover(id: string) {
		openBucketPopoverFor = openBucketPopoverFor === id ? null : id;
	}

	function setBucketHide(id: string, hide: boolean) {
		bucketState = { ...bucketState, [id]: { ...bucketState[id], hide } };
	}

	function setBucketIso(id: string, iso: boolean) {
		bucketState = { ...bucketState, [id]: { ...bucketState[id], iso } };
	}

	// The one shared visibility predicate every bucket goes through - no
	// per-bucket special-casing. Hide always wins; multiple simultaneously
	// iso-active buckets compose as OR/union (that's the actual point of
	// isolate: "show me anything in ANY of these buckets at once", not an
	// intersection), never AND.
	function isVisible(r: WordResult): boolean {
		const hideActive = BUCKETS.filter((b) => bucketState[b.id]?.hide);
		const isoActive = BUCKETS.filter((b) => bucketState[b.id]?.iso);
		if (hideActive.some((b) => b.test(r))) return false;
		if (isoActive.length > 0 && !isoActive.some((b) => b.test(r))) return false;
		return true;
	}

	function bucketCount(bucket: Bucket): number {
		// Always against the FULL unfiltered result set, not filteredResults
		// - the point is showing "Garbage (8)" regardless of what other
		// filters are currently active, so the user knows how many are
		// waiting for review even while looking at something else.
		if (!analysis) return 0;
		return analysis.results.filter(bucket.test).length;
	}

	// --- Sorting ------------------------------------------------------------
	// Persisted the same way the filters above are (global per-browser, not
	// per-analysis) - a tri-state toggle per column: first click sorts
	// ascending, second flips to descending, third clears back to the
	// server's natural order (count descending - see AnalysisResponse.
	// results' ordering, router.py).
	type SortColumn = 'word' | 'count' | 'source' | 'familiarity' | null;
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

	function compareResults(a: WordResult, b: WordResult): number {
		let cmp = 0;
		switch (sortColumn) {
			case 'word':
				// Plain codepoint comparison, deliberately NOT localeCompare
				// with a 'zh' locale - Chinese collation there sorts by
				// pinyin, which is exactly what wasn't wanted here (pinyin
				// support is a separate, not-yet-designed piece of this app -
				// see CLAUDE.md). This is a real but non-phonetic ordering,
				// stable and locale-independent.
				cmp = a.word < b.word ? -1 : a.word > b.word ? 1 : 0;
				break;
			case 'count':
				cmp = a.count - b.count;
				break;
			case 'source':
				// Sorts by the DISPLAYED label (sourceLabel), not the raw
				// source key - e.g. 'dag' and legacy 'trie' both show as
				// "segmenter" and should sort adjacently, matching what's
				// actually in the column.
				cmp = sourceLabel(a.source).localeCompare(sourceLabel(b.source));
				break;
			case 'familiarity': {
				// Unknown (null) sorts as lower than any scored value (1-5).
				const fa = currentFamiliarity(a) ?? -1;
				const fb = currentFamiliarity(b) ?? -1;
				cmp = fa - fb;
				break;
			}
		}
		return sortDirection === 'desc' ? -cmp : cmp;
	}

	const filteredResults = $derived(() => {
		if (!analysis) return [];
		const query = searchQuery.trim();
		const filtered = analysis.results.filter((r) => {
			if (query && !r.word.includes(query)) return false;
			// "Search all" bypasses every other filter below once there's an
			// active query; "search filtered" (default) just narrows within
			// whatever the other filters already allow. Unchanged from
			// before this rework - the search box stays its own predicate.
			if (query && searchScope === 'all') return true;
			if (!isVisible(r)) return false;
			// Familiarity threshold - unchanged, stays its own separate
			// predicate, not part of the bucket registry (per earlier
			// discussion).
			const familiarity = knownWords[r.word] ?? r.familiarity;
			if (familiarity !== null && familiarity !== undefined && familiarity >= minFamiliarityFilter) return false;
			return true;
		});
		// `filter` already returns a fresh array, so sorting it in place here
		// doesn't touch analysis.results (which stays in the server's
		// original count-descending order - see AnalysisResponse.results,
		// router.py).
		return sortColumn ? filtered.sort(compareResults) : filtered;
	});

	// Persist filter preferences (not search text - see FILTER_STORAGE_KEY
	// comment) on every change, global per-browser rather than per-analysis.
	$effect(() => {
		if (!browser) return;
		try {
			const toStore: StoredFilters = { buckets: bucketState, minFamiliarityFilter, searchScope, sortColumn, sortDirection };
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
			// getAnalysis first (not parallel with the rest) - the scoped
			// list endpoints below need analysis.input_text_id to resolve
			// text-scoped entries, which isn't known until this resolves.
			analysis = await api.getAnalysis(id) as Analysis;

			const [knownWordsData, garbageData, userWordsData, starredData] = await Promise.all([
				api.listKnownWords() as Promise<any[]>,
				api.listGarbageWords() as Promise<any[]>,
				// Global only (bare, no viewing context) - this Set drives the
				// results-table "+ Add word" quick button, which always writes
				// global, so its "already added" state must reflect global
				// specifically, not whatever scope happens to resolve for the
				// current text/analysis (a word could have only a text-scoped
				// entry, which would otherwise make the button look "filled"
				// while removing it 404s trying to delete a global row that
				// doesn't exist).
				api.listUserWords() as Promise<any[]>,
				api.listStarredWords() as Promise<any[]>,
			]);

			const kwMap: Record<string, number | null> = {};
			for (const kw of knownWordsData) {
				kwMap[kw.word] = kw.familiarity;
			}
			knownWords = kwMap;

			// Mirrors service.get_user_garbage_words: a word counts as garbage
			// if some row marks it so (system-default or the user's own) and
			// no override row (added by unmarking a system-default word - see
			// unmarkGarbage) cancels it back out.
			const overrideWords = new Set(
				garbageData.filter((g: any) => g.is_override).map((g: any) => g.word)
			);
			garbageWords = new Set(
				garbageData
					.filter((g: any) => !g.is_override && !overrideWords.has(g.word))
					.map((g: any) => g.word)
			);

			userWords = new Set(userWordsData.map((uw: any) => uw.word));
			userWordAffectsDag = Object.fromEntries(userWordsData.map((uw: any) => [uw.word, uw.affects_dag]));
			starredWords = new Set(starredData.map((s: any) => s.word));
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load analysis';
		} finally {
			loading = false;
		}
	});

	// Always global - familiarity has no scope (see KnownWord's docstring,
	// models.py) - so there's no ctx to pass, unlike user-word.
	async function setFamiliarity(word: string, familiarity: number | null) {
		updatingWord = word;
		try {
			await api.upsertKnownWord(word, familiarity);
			knownWords = { ...knownWords, [word]: familiarity };
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update word';
		} finally {
			updatingWord = '';
		}
	}

	// Garbage words stay in the persisted analysis results like everything
	// else (see WordResult.is_garbage) - marking a word garbage just adds it
	// to the user's garbage-word list, which the "hide garbage" filter
	// (default on) uses to hide it from the default view. Fully reversible,
	// same toggle treatment as Star - see unmarkGarbage below.
	async function markAsGarbage(word: string) {
		togglingGarbage = word;
		try {
			await api.createGarbageWord(word);
			garbageWords = new Set([...garbageWords, word]);
		} catch (e: unknown) {
			const message = e instanceof Error ? e.message : '';
			if (message.toLowerCase().includes('already exists')) {
				garbageWords = new Set([...garbageWords, word]);
			} else {
				error = message || 'Failed to mark as garbage';
			}
		} finally {
			togglingGarbage = '';
		}
	}

	// Reverses whatever is currently making `word` show as garbage - the
	// user's own marking, or a system-default one (cancelled out server-side
	// via an override row, transparent to the frontend - see
	// unmark_garbage_word's docstring, router.py).
	async function unmarkGarbage(word: string) {
		togglingGarbage = word;
		try {
			await api.unmarkGarbageWord(word);
			const next = new Set(garbageWords);
			next.delete(word);
			garbageWords = next;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to unmark as garbage';
		} finally {
			togglingGarbage = '';
		}
	}

	// Desktop-only (see Phase 1 plan notes): clicking a row opens its info
	// panel, unless the click originated on an actual interactive element
	// within the row (button/link/input/select), which should handle itself.
	function handleRowClick(event: MouseEvent, word: string) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		openWordDetail(word);
	}

	function scopePriority(entry: { scope_analysis_id: number | null; scope_input_text_id: number | null }): number {
		if (entry.scope_analysis_id != null) return 2;
		if (entry.scope_input_text_id != null) return 1;
		return 0;
	}

	// Mirrors the backend's most-specific-first ordering (router.py's
	// _sort_most_specific_first) client-side - used wherever a UserWord
	// list needs re-sorting after a local mutation, so it doesn't require a
	// full refetch to stay in the same order the initial load had.
	function sortMostSpecificFirst<T extends { scope_analysis_id: number | null; scope_input_text_id: number | null }>(rows: T[]): T[] {
		return [...rows].sort((a, b) => scopePriority(b) - scopePriority(a));
	}

	// Mirrors the backend's _resolve_scope_columns (router.py) client-side,
	// no HTTP - turns a scope choice + the current viewing context into the
	// (scope_analysis_id, scope_input_text_id) pair a row at that scope has.
	function resolveScopeColumns(scope: Scope, analysisId?: number, inputTextId?: number): { scope_analysis_id: number | null; scope_input_text_id: number | null } {
		if (scope === 'analysis') return { scope_analysis_id: analysisId ?? null, scope_input_text_id: null };
		if (scope === 'text') return { scope_analysis_id: null, scope_input_text_id: inputTextId ?? null };
		return { scope_analysis_id: null, scope_input_text_id: null };
	}

	function columnsMatch(
		a: { scope_analysis_id: number | null; scope_input_text_id: number | null },
		b: { scope_analysis_id: number | null; scope_input_text_id: number | null }
	): boolean {
		return a.scope_analysis_id === b.scope_analysis_id && a.scope_input_text_id === b.scope_input_text_id;
	}

	const ALL_SCOPES: { value: Scope; label: string }[] = [
		{ value: 'analysis', label: 'This analysis' },
		{ value: 'text', label: 'This text' },
		{ value: 'global', label: 'Global' },
	];

	function scopeLabel(entry: { scope_analysis_id: number | null; scope_input_text_id: number | null }): string {
		if (entry.scope_analysis_id != null) return 'This analysis';
		if (entry.scope_input_text_id != null) return `This text: ${analysis?.title ?? 'Untitled'}`;
		return 'Global';
	}

	// Which of the three canonical scopes have no matching entry yet, for
	// the "+ Add entry"/tri-state "no row here" affordances.
	function missingScopes(entries: { scope_analysis_id: number | null; scope_input_text_id: number | null }[]): { value: Scope; label: string }[] {
		return ALL_SCOPES.filter((s) => {
			const cols = resolveScopeColumns(s.value, id, analysis?.input_text_id);
			return !entries.some((e) => columnsMatch(e, cols));
		});
	}

	// The "+ Add entry" scope selector should always default to the
	// BROADEST still-available scope, not the narrowest - ALL_SCOPES (and
	// therefore missingScopes, which filters it) is ordered most-specific
	// first (analysis, text, global), so the least specific missing scope
	// is simply the last entry in that filtered list. null when every scope
	// already has an entry (nothing left to add).
	function leastSpecificMissingScope(entries: { scope_analysis_id: number | null; scope_input_text_id: number | null }[]): Scope | null {
		const missing = missingScopes(entries);
		return missing.length > 0 ? missing[missing.length - 1].value : null;
	}

	// Mirrors the backend's _resolve_word_visibility (router.py) client-side,
	// no HTTP - walks the same most-specific-first ordering already used
	// elsewhere (sortMostSpecificFirst) and takes the first row's own value,
	// since presence of a WordVisibility row already means "opinion" (no
	// tri-state/NULL-skipping needed here, unlike affects_dag - see
	// WordVisibility's docstring, models.py).
	function resolveVisibilityFromEntries(entries: WordVisibilityEntry[]): { is_hidden: boolean; hidden_governing_scope: string } {
		if (entries.length === 0) return { is_hidden: false, hidden_governing_scope: 'default' };
		const winner = sortMostSpecificFirst(entries)[0];
		const scope = winner.scope_analysis_id != null ? 'analysis' : winner.scope_input_text_id != null ? 'text' : 'global';
		return { is_hidden: winner.hidden, hidden_governing_scope: scope };
	}

	// Patches the resolved is_hidden/hidden_governing_scope directly onto
	// analysis.results after a local WordVisibility mutation, so the
	// results-table quick-action's icon/badge update immediately without a
	// full analysis refetch - same "patch locally" approach already used
	// for userWords/userWordAffectsDag elsewhere on this page.
	function patchResolvedVisibility(word: string, entries: WordVisibilityEntry[]) {
		if (!analysis) return;
		const resolved = resolveVisibilityFromEntries(entries);
		analysis = { ...analysis, results: analysis.results.map((r) => r.word === word ? { ...r, ...resolved } : r) };
	}

	function scopeContext(scope: Scope): api.ScopeContext {
		if (scope === 'analysis') return { analysisId: id, scope: 'analysis' };
		if (scope === 'text') return { inputTextId: analysis?.input_text_id, scope: 'text' };
		return { scope: 'global' };
	}

	interface VisibilityMenuAction {
		kind: 'set' | 'remove';
		scope: Scope;
		targetHidden?: boolean;
		label: string;
	}

	// One function, not a lookup table of special cases - see the row/card
	// quick-action's docstring comment near its snippet for the rule this
	// implements verbatim.
	function buildVisibilityMenu(resolvedHidden: boolean, rows: WordVisibilityEntry[]): VisibilityMenuAction[] {
		const targetHidden = !resolvedHidden;
		const scopeText: Record<Scope, string> = { global: 'globally', text: 'for this text', analysis: 'for this analysis' };
		const actions: VisibilityMenuAction[] = [];
		for (const scope of ['global', 'text', 'analysis'] as Scope[]) {
			const cols = resolveScopeColumns(scope, id, analysis?.input_text_id);
			const rowAtScope = rows.find((r) => columnsMatch(r, cols));
			// (a)+(b): the "set" action, omitted if a row already exists at
			// this exact scope with this exact target value (a no-op).
			const isNoOp = rowAtScope !== undefined && rowAtScope.hidden === targetHidden;
			if (!isNoOp) {
				actions.push({ kind: 'set', scope, targetHidden, label: `${targetHidden ? 'Hide' : 'Show'} ${scopeText[scope]}` });
			}
			// (c): text/analysis only (never global - there's no broader
			// fallback beyond global to "remove" back to). Independent of
			// (b) - offered whenever a row is present at this scope, even if
			// the set action above was just omitted as a no-op.
			if (scope !== 'global' && rowAtScope !== undefined) {
				actions.push({ kind: 'remove', scope, label: `Remove this ${scope === 'text' ? "text's" : "analysis's"} override` });
			}
		}
		return actions;
	}

	// Lazily fetches + caches the up-to-3 raw WordVisibility rows for a word
	// (via getWordDetail, same endpoint the panel uses) the first time its
	// quick-action menu opens - only one menu open at a time.
	async function toggleVisibilityMenu(word: string) {
		if (visibilityMenuOpenFor === word) {
			visibilityMenuOpenFor = null;
			return;
		}
		visibilityMenuOpenFor = word;
		if (visibilityRowsByWord[word]) return;
		loadingVisibilityFor = new Set([...loadingVisibilityFor, word]);
		try {
			const detail = await api.getWordDetail(word, id, analysis?.input_text_id) as WordDetail;
			visibilityRowsByWord = { ...visibilityRowsByWord, [word]: detail.word_visibility };
		} catch (e: unknown) {
			visibilityRowsByWord = { ...visibilityRowsByWord, [word]: [] };
		} finally {
			const next = new Set(loadingVisibilityFor);
			next.delete(word);
			loadingVisibilityFor = next;
		}
	}

	async function applyVisibilityAction(word: string, action: VisibilityMenuAction) {
		togglingVisibilityAction = word;
		try {
			const cols = resolveScopeColumns(action.scope, id, analysis?.input_text_id);
			let nextRows: WordVisibilityEntry[];
			if (action.kind === 'set') {
				const updated = await api.upsertWordVisibility(word, action.targetHidden!, scopeContext(action.scope)) as WordVisibilityEntry;
				nextRows = sortMostSpecificFirst([...(visibilityRowsByWord[word] ?? []).filter((r) => !columnsMatch(r, cols)), updated]);
			} else {
				await api.deleteWordVisibility(word, cols.scope_analysis_id, cols.scope_input_text_id);
				nextRows = (visibilityRowsByWord[word] ?? []).filter((r) => !columnsMatch(r, cols));
			}
			visibilityRowsByWord = { ...visibilityRowsByWord, [word]: nextRows };
			patchResolvedVisibility(word, nextRows);
			if (selectedWord?.word === word) {
				selectedWord = { ...selectedWord, word_visibility: nextRows };
			}
			visibilityMenuOpenFor = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update visibility';
		} finally {
			togglingVisibilityAction = null;
		}
	}

	// Panel's own Visibility section - unlike UserWord's affects_dag, all
	// three scope slots (including analysis) are shown/editable here (see
	// the section's template comment for why).
	function visibilityEntryAtScope(scope: Scope): WordVisibilityEntry | undefined {
		if (!selectedWord) return undefined;
		const cols = resolveScopeColumns(scope, id, analysis?.input_text_id);
		return selectedWord.word_visibility.find((e) => columnsMatch(e, cols));
	}

	async function setVisibility(scope: Scope, hidden: boolean) {
		if (!selectedWord) return;
		togglingVisibilityScope = scope;
		try {
			const updated = await api.upsertWordVisibility(selectedWord.word, hidden, scopeContext(scope)) as WordVisibilityEntry;
			const cols = resolveScopeColumns(scope, id, analysis?.input_text_id);
			const nextRows = sortMostSpecificFirst([...selectedWord.word_visibility.filter((e) => !columnsMatch(e, cols)), updated]);
			selectedWord = { ...selectedWord, word_visibility: nextRows };
			visibilityRowsByWord = { ...visibilityRowsByWord, [selectedWord.word]: nextRows };
			patchResolvedVisibility(selectedWord.word, nextRows);
			addingVisibilityOverrideFor = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update visibility';
		} finally {
			togglingVisibilityScope = null;
		}
	}

	async function removeVisibilityOverride(scope: Scope) {
		if (!selectedWord) return;
		togglingVisibilityScope = scope;
		try {
			const cols = resolveScopeColumns(scope, id, analysis?.input_text_id);
			await api.deleteWordVisibility(selectedWord.word, cols.scope_analysis_id, cols.scope_input_text_id);
			const nextRows = selectedWord.word_visibility.filter((e) => !columnsMatch(e, cols));
			selectedWord = { ...selectedWord, word_visibility: nextRows };
			visibilityRowsByWord = { ...visibilityRowsByWord, [selectedWord.word]: nextRows };
			patchResolvedVisibility(selectedWord.word, nextRows);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove visibility override';
		} finally {
			togglingVisibilityScope = null;
		}
	}

	function visibilitySummary(entries: WordVisibilityEntry[]): string {
		const { is_hidden, hidden_governing_scope } = resolveVisibilityFromEntries(entries);
		if (hidden_governing_scope === 'default') return 'Shown (inherited - no override set)';
		if (hidden_governing_scope === 'global') return is_hidden ? 'Hidden (set globally)' : 'Shown (set globally)';
		const scopeText = hidden_governing_scope === 'text' ? 'for this text' : 'for this analysis';
		return is_hidden ? `Hidden (overridden ${scopeText})` : `Shown (overridden ${scopeText})`;
	}

	// ctx omitted by row/card (global, unchanged); the panel's own quick
	// bookmark icon passes userWordScope. Only ever updates the global-only
	// `userWords` Set when the write actually targeted global - see its own
	// comment in onMount for why that Set must stay global-specific.
	// ctx omitted by row/card (global, unchanged; always defaults to
	// affects_dag=true server-side, a sensible "just add it" default).
	async function addUserWord(word: string, ctx?: api.ScopeContext) {
		addingUserWord = word;
		const effectiveScope = ctx?.scope ?? 'global';
		try {
			const created = await api.createUserWord(word, undefined, ctx) as UserWordDetail;
			if (effectiveScope === 'global') {
				userWords = new Set([...userWords, word]);
				userWordAffectsDag = { ...userWordAffectsDag, [word]: created.affects_dag };
			}
			if (selectedWord?.word === word) {
				selectedWord = { ...selectedWord, user_words: sortMostSpecificFirst([...selectedWord.user_words, created]) };
			}
		} catch (e: unknown) {
			// If it already exists (e.g. added from another session), just
			// reflect that in the UI instead of surfacing an error banner.
			const message = e instanceof Error ? e.message : '';
			if (message.toLowerCase().includes('already exists')) {
				if (effectiveScope === 'global') {
					userWords = new Set([...userWords, word]);
				}
			} else {
				error = message || 'Failed to add word to your dictionary';
			}
		} finally {
			addingUserWord = '';
		}
	}

	// Deletes the exact scoped row - row/card omit (global, unchanged); the
	// panel's own quick bookmark icon passes the entry actually loaded at
	// userWordScope (not userWordScope itself, which is only for where a
	// NEW entry should go).
	async function removeUserWord(word: string, scopeAnalysisId?: number | null, scopeInputTextId?: number | null) {
		addingUserWord = word;
		try {
			await api.deleteUserWord(word, scopeAnalysisId, scopeInputTextId);
			if (scopeAnalysisId == null && scopeInputTextId == null) {
				const next = new Set(userWords);
				next.delete(word);
				userWords = next;
				const nextAffects = { ...userWordAffectsDag };
				delete nextAffects[word];
				userWordAffectsDag = nextAffects;
			}
			if (selectedWord?.word === word) {
				const cols = { scope_analysis_id: scopeAnalysisId ?? null, scope_input_text_id: scopeInputTextId ?? null };
				selectedWord = { ...selectedWord, user_words: selectedWord.user_words.filter((e) => !columnsMatch(e, cols)) };
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove word from your dictionary';
		} finally {
			addingUserWord = '';
		}
	}

	function startEditingEntry(entry: UserWordDetail) {
		entryDrafts = { ...entryDrafts, [entry.id]: {
			pronunciation: entry.pronunciation ?? '', meaning: entry.meaning ?? '', notes: entry.notes ?? '',
			affectsDag: entry.affects_dag,
		} };
		entryEditingIds = new Set([...entryEditingIds, entry.id]);
	}

	function cancelEditingEntry(entryId: number) {
		const next = new Set(entryEditingIds);
		next.delete(entryId);
		entryEditingIds = next;
	}

	function scopeContextForEntry(entry: UserWordDetail): api.ScopeContext {
		if (entry.scope_analysis_id != null) return { analysisId: entry.scope_analysis_id, scope: 'analysis' };
		if (entry.scope_input_text_id != null) return { inputTextId: entry.scope_input_text_id, scope: 'text' };
		return { scope: 'global' };
	}

	async function saveEntry(entry: UserWordDetail) {
		if (!selectedWord) return;
		savingEntryId = entry.id;
		try {
			const draft = entryDrafts[entry.id];
			const isAnalysisScoped = entry.scope_analysis_id != null;
			const fields: { pronunciation: string | null; meaning: string | null; notes: string | null; affects_dag?: boolean | null } = {
				pronunciation: draft.pronunciation || null,
				meaning: draft.meaning || null,
				notes: draft.notes || null,
			};
			// affects_dag is never sent for an analysis-scoped entry - it has
			// no observable effect there, so there's nothing to write (see
			// UserWord's docstring, models.py) and no toggle is shown for it.
			if (!isAnalysisScoped) fields.affects_dag = draft.affectsDag;
			const updated = await api.upsertUserWordDetail(selectedWord.word, fields, scopeContextForEntry(entry)) as UserWordDetail;
			selectedWord = { ...selectedWord, user_words: selectedWord.user_words.map((e) => e.id === entry.id ? updated : e) };
			if (entry.scope_analysis_id == null && entry.scope_input_text_id == null) {
				userWords = new Set([...userWords, selectedWord.word]);
				userWordAffectsDag = { ...userWordAffectsDag, [selectedWord.word]: updated.affects_dag };
			}
			cancelEditingEntry(entry.id);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to save word details';
		} finally {
			savingEntryId = null;
		}
	}

	async function deleteEntry(entry: UserWordDetail) {
		if (!selectedWord) return;
		savingEntryId = entry.id;
		try {
			await api.deleteUserWord(selectedWord.word, entry.scope_analysis_id, entry.scope_input_text_id);
			selectedWord = { ...selectedWord, user_words: selectedWord.user_words.filter((e) => e.id !== entry.id) };
			if (entry.scope_analysis_id == null && entry.scope_input_text_id == null) {
				const next = new Set(userWords);
				next.delete(selectedWord.word);
				userWords = next;
				const nextAffects = { ...userWordAffectsDag };
				delete nextAffects[selectedWord.word];
				userWordAffectsDag = nextAffects;
			}
			// Deleting an entry frees up its scope - re-derive so the
			// "+ Add entry" selector reflects the now-broader set of missing
			// scopes (e.g. deleting the global entry should offer Global
			// again, not stay stuck on whatever scope was last picked).
			const leastSpecific = leastSpecificMissingScope(selectedWord.user_words);
			if (leastSpecific) userWordScope = leastSpecific;
			cancelEditingEntry(entry.id);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove word from your dictionary';
		} finally {
			savingEntryId = null;
		}
	}

	function startAddingNewEntry() {
		newEntryDraft = { pronunciation: '', meaning: '', notes: '', affectsDag: true };
		addingNewEntry = true;
	}

	async function saveNewEntry() {
		if (!selectedWord) return;
		savingEntryId = -1; // sentinel: "adding", not any real row id
		try {
			const isAnalysisScoped = userWordScope === 'analysis';
			const fields: { pronunciation: string | null; meaning: string | null; notes: string | null; affects_dag?: boolean | null } = {
				pronunciation: newEntryDraft.pronunciation || null,
				meaning: newEntryDraft.meaning || null,
				notes: newEntryDraft.notes || null,
			};
			if (!isAnalysisScoped) fields.affects_dag = newEntryDraft.affectsDag;
			const created = await api.upsertUserWordDetail(selectedWord.word, fields, {
				analysisId: id, inputTextId: analysis?.input_text_id, scope: userWordScope,
			}) as UserWordDetail;
			selectedWord = { ...selectedWord, user_words: sortMostSpecificFirst([...selectedWord.user_words, created]) };
			if (userWordScope === 'global') {
				userWords = new Set([...userWords, selectedWord.word]);
				userWordAffectsDag = { ...userWordAffectsDag, [selectedWord.word]: created.affects_dag };
			}
			addingNewEntry = false;
			const leastSpecific = leastSpecificMissingScope(selectedWord.user_words);
			if (leastSpecific) userWordScope = leastSpecific;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add word to your dictionary';
		} finally {
			savingEntryId = null;
		}
	}

	// Starred words are a simple global toggle (see StarredWord's docstring -
	// no scoping, no dedicated note-editing surface here, same "quick
	// action" treatment as the row's other quick-toggle buttons rather than
	// the panel's fuller note-editing flow).
	async function markAsStarred(word: string) {
		togglingStarred = word;
		try {
			await api.createStarredWord(word);
			starredWords = new Set([...starredWords, word]);
		} catch (e: unknown) {
			const message = e instanceof Error ? e.message : '';
			if (message.toLowerCase().includes('already exists')) {
				starredWords = new Set([...starredWords, word]);
			} else {
				error = message || 'Failed to star word';
			}
		} finally {
			togglingStarred = '';
		}
	}

	async function unmarkStarred(word: string) {
		togglingStarred = word;
		try {
			await api.deleteStarredWord(word);
			const next = new Set(starredWords);
			next.delete(word);
			starredWords = next;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to unstar word';
		} finally {
			togglingStarred = '';
		}
	}

	async function openWordDetail(word: string) {
		loadingDetail = true;
		selectedWord = null;
		entryEditingIds = new Set();
		entryDrafts = {};
		addingNewEntry = false;
		userWordScope = 'global';
		addingVisibilityOverrideFor = null;
		// Desktop only in practice - the matching mobile card is hidden
		// (display:none) at that viewport, so scrollIntoView on it is a
		// harmless no-op there.
		requestAnimationFrame(() => {
			document.querySelector(`[data-word="${CSS.escape(word)}"]`)
				?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
		});
		try {
			selectedWord = await api.getWordDetail(word, id, analysis?.input_text_id) as WordDetail;
			// Default the "+ Add entry" scope selector to the broadest scope
			// that doesn't already have an entry (global unless that's taken,
			// then text, then analysis) - see leastSpecificMissingScope.
			const leastSpecific = leastSpecificMissingScope(selectedWord.user_words);
			if (leastSpecific) userWordScope = leastSpecific;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load word detail';
		} finally {
			loadingDetail = false;
		}
	}

	// Fetches + caches a word's context on first request; a no-op on repeat
	// calls (toggling closed and back open shouldn't re-fetch).
	async function ensureContextLoaded(word: string) {
		if (contextByWord[word] || loadingContextFor.has(word)) return;
		loadingContextFor = new Set([...loadingContextFor, word]);
		try {
			const context = await api.getWordContext(id, word) as { occurrences: WordOccurrence[] };
			contextByWord = { ...contextByWord, [word]: context.occurrences };
		} catch (e: unknown) {
			contextByWord = { ...contextByWord, [word]: [] };
		} finally {
			const next = new Set(loadingContextFor);
			next.delete(word);
			loadingContextFor = next;
		}
	}

	// Desktop: chevron toggles an expanded strip beneath the row.
	function toggleContext(word: string) {
		const next = new Set(expandedContext);
		if (next.has(word)) {
			next.delete(word);
		} else {
			next.add(word);
			ensureContextLoaded(word);
		}
		expandedContext = next;
	}

	// Independent of user_words - a word doesn't need to be in the user's
	// dictionary to have sample sentences (see SampleSentence's docstring,
	// models.py). Copy the relevant part of a context occurrence manually
	// and paste it in here.
	async function addSampleSentence() {
		if (!selectedWord || !newSentenceDraft.trim()) return;
		savingSentence = true;
		try {
			const created = await api.addSampleSentence(selectedWord.word, newSentenceDraft.trim()) as SampleSentence;
			selectedWord = { ...selectedWord, sample_sentences: [...selectedWord.sample_sentences, created] };
			newSentenceDraft = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add sample sentence';
		} finally {
			savingSentence = false;
		}
	}

	async function removeSampleSentence(sentenceId: number) {
		if (!selectedWord) return;
		deletingSentenceId = sentenceId;
		try {
			await api.deleteSampleSentence(sentenceId);
			selectedWord = {
				...selectedWord,
				sample_sentences: selectedWord.sample_sentences.filter((s) => s.id !== sentenceId),
			};
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove sample sentence';
		} finally {
			deletingSentenceId = null;
		}
	}

	function familiarityLabel(score: number | null): string {
		if (score === null || score === undefined) return 'Unknown';
		const labels: Record<number, string> = {
			1: 'Seen it',
			2: 'Recognize',
			3: 'Know it',
			4: 'Know well',
			5: 'Mastered',
		};
		return labels[score] ?? 'Unknown';
	}

	function familiarityColor(score: number | null): string {
		if (score === null || score === undefined) return 'bg-gray-100 text-gray-600';
		const colors: Record<number, string> = {
			1: 'bg-red-100 text-red-700',
			2: 'bg-orange-100 text-orange-700',
			3: 'bg-yellow-100 text-yellow-700',
			4: 'bg-green-100 text-green-700',
			5: 'bg-emerald-100 text-emerald-700',
		};
		return colors[score] ?? 'bg-gray-100 text-gray-600';
	}

	// Tooltip for the results-table/card bookmark button, which only ever
	// reflects the word's GLOBAL UserWord entry (see userWordAffectsDag's
	// own comment) - distinguishes all three tri-state values (see
	// UserWord.affects_dag's docstring, models.py).
	function userWordTooltip(word: string): string {
		const v = userWordAffectsDag[word];
		if (v === false) return 'In your dictionary, excluded from segmentation — click to remove';
		if (v === null || v === undefined) return 'In your dictionary, no segmentation preference set — click to remove';
		return 'In your dictionary — click to remove';
	}

	function currentFamiliarity(result: WordResult): number | null {
		if (result.word in knownWords) return knownWords[result.word];
		return result.familiarity;
	}

	function sourceLabel(source: string): string {
		const labels: Record<string, string> = {
			dag: 'segmenter',
			overlay: 'your word',
			token: 'unknown seq.',
			unknown: 'unknown',
			longest_match_only: 'extra match',
			trie: 'segmenter', // legacy label from before the DAG segmenter
		};
		return labels[source] ?? source;
	}

	function sourceColor(source: string): string {
		const colors: Record<string, string> = {
			dag: 'bg-blue-100 text-blue-700',
			trie: 'bg-blue-100 text-blue-700',
			overlay: 'bg-indigo-100 text-indigo-700',
			token: 'bg-purple-100 text-purple-700',
			unknown: 'bg-gray-100 text-gray-600',
			longest_match_only: 'bg-amber-100 text-amber-700',
		};
		return colors[source] ?? 'bg-gray-100 text-gray-600';
	}

	function toggleInfo(word: string) {
		const next = new Set(expandedInfo);
		if (next.has(word)) {
			next.delete(word);
		} else {
			next.add(word);
			// Context is folded into this same accordion section on mobile
			// (see the sm:hidden card list) rather than a separate toggle.
			ensureContextLoaded(word);
		}
		expandedInfo = next;
	}

	function toggleActions(word: string) {
		const next = new Set(expandedActions);
		if (next.has(word)) next.delete(word);
		else next.add(word);
		expandedActions = next;
	}
</script>

{#snippet iconInfo()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5">
		<circle cx="10" cy="10" r="8" />
		<circle cx="10" cy="6.5" r="0.9" fill="currentColor" stroke="none" />
		<path d="M10 9.5v5" stroke-linecap="round" />
	</svg>
{/snippet}

{#snippet iconChevron(expanded: boolean)}
	<svg
		class="w-4 h-4 transition-transform {expanded ? 'rotate-180' : ''}"
		viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
	>
		<path d="M5 7.5l5 5 5-5" />
	</svg>
{/snippet}

<!-- Sortable desktop table header - reuses iconChevron (rotated = pointing
     up = ascending, unrotated = pointing down = descending) rather than a
     new arrow glyph. Only rendered when this column is the active sort, so
     inactive columns stay unmarked. -->
{#snippet sortHeader(label: string, column: 'word' | 'count' | 'source' | 'familiarity')}
	<button
		onclick={() => toggleSort(column)}
		class="flex items-center gap-1 hover:text-blue-600 {sortColumn === column ? 'text-blue-600' : ''}"
		title="Sort by {label}"
	>
		{label}
		{#if sortColumn === column}
			{@render iconChevron(sortDirection === 'asc')}
		{/if}
	</button>
{/snippet}

{#snippet contextList(word: string)}
	<!-- Where this word occurs in the source text. Not every match type has
	     stored positions or found any live-search matches (see the backend's
	     get_word_context docstring) - "not available" covers both, rather
	     than distinguishing them for what's already an edge case. Capped
	     height + its own scroll so a word with dozens of occurrences doesn't
	     take over the page/card. -->
	{#if loadingContextFor.has(word)}
		<p class="text-sm text-gray-400">Loading context...</p>
	{:else if (contextByWord[word]?.length ?? 0) > 0}
		<div class="space-y-2 max-h-64 overflow-y-auto pr-1">
			{#each contextByWord[word] as occ}
				<p class="text-sm leading-relaxed">
					<span class="text-gray-500">{occ.before}</span><mark class="bg-yellow-200 rounded px-0.5">{occ.match}</mark><span class="text-gray-500">{occ.after}</span>
				</p>
			{/each}
		</div>
	{:else}
		<p class="text-sm text-gray-400">Context not available for this word.</p>
	{/if}
{/snippet}

{#snippet iconBookmark(filled: boolean)}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.3">
		<path d="M5 3.5A1.5 1.5 0 0 1 6.5 2h7A1.5 1.5 0 0 1 15 3.5v13l-5-3-5 3v-13Z" stroke-linejoin="round" />
	</svg>
{/snippet}

{#snippet iconStar(filled: boolean)}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.3" stroke-linejoin="round">
		<path d="M10 2.5l2.2 4.6 5 .7-3.6 3.6.85 5-4.45-2.4-4.45 2.4.85-5-3.6-3.6 5-.7L10 2.5Z" />
	</svg>
{/snippet}

{#snippet iconTrash()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
		<path d="M4 5.5h12M8 5.5V4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5M6 5.5l.6 10.2a1 1 0 0 0 1 .8h4.8a1 1 0 0 0 1-.8l.6-10.2M8.5 8.5v5M11.5 8.5v5" />
	</svg>
{/snippet}

{#snippet iconPlusMinus(expanded: boolean)}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
		<path d="M4 10h12" />
		{#if !expanded}
			<path d="M10 4v12" />
		{/if}
	</svg>
{/snippet}

{#snippet iconHamburger(expanded: boolean)}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
		{#if expanded}
			<path d="M5 5l10 10M15 5L5 15" />
		{:else}
			<path d="M4 6h12M4 10h12M4 14h12" />
		{/if}
	</svg>
{/snippet}

{#snippet iconEye(open: boolean)}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10Z" />
		<circle cx="10" cy="10" r="2.25" />
		{#if !open}
			<line x1="3" y1="16.5" x2="17" y2="3.5" />
		{/if}
	</svg>
{/snippet}

<!-- Small letter badge for hidden_governing_scope (G/T/A) - there is no
     existing icon-badge system for scope in this app (scope elsewhere is
     shown via a text-label <select>, e.g. scopeLabel()/ALL_SCOPES below) -
     this is a new, minimal visual purpose-built for the visibility
     quick-action, not a reuse of anything pre-existing. -->
{#snippet scopeBadge(scope: string)}
	{#if scope !== 'default'}
		<span
			class="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-white border border-current text-[8px] leading-[10px] font-bold flex items-center justify-center pointer-events-none"
			title={scope === 'global' ? 'Global' : scope === 'text' ? 'This text' : 'This analysis'}
		>{scope === 'global' ? 'G' : scope === 'text' ? 'T' : 'A'}</span>
	{/if}
{/snippet}

<!-- Filter chip icons. Garbage/Hidden/User words/Starred reuse the exact
     icons their own row/card quick-actions already use (iconTrash/iconEye/
     iconBookmark/iconStar) - the remaining buckets (extra match/
     unrecognized/unknown/dag/non-Chinese) have no pre-existing icon
     anywhere in this app, so these are new, minimal, purpose-built shapes,
     kept in the same stroke-width/viewBox style as the rest of the icon
     set. iconLatin reuses the small-letter-badge visual language from
     scopeBadge above (a plain glyph in a circle) as a deliberate callback. -->
{#snippet iconPlus()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
		<circle cx="10" cy="10" r="8" />
		<path d="M10 6.5v7M6.5 10h7" />
	</svg>
{/snippet}

{#snippet iconSequence()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
		<circle cx="4" cy="10" r="1.3" fill="currentColor" stroke="none" />
		<circle cx="10" cy="10" r="1.3" fill="currentColor" stroke="none" />
		<circle cx="16" cy="10" r="1.3" fill="currentColor" stroke="none" />
	</svg>
{/snippet}

{#snippet iconQuestion()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
		<circle cx="10" cy="10" r="8" />
		<path d="M7.5 8a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.4" />
		<circle cx="10" cy="14" r="0.4" fill="currentColor" stroke="none" />
	</svg>
{/snippet}

{#snippet iconSegments()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
		<rect x="2.5" y="6" width="4" height="8" rx="0.5" />
		<rect x="8" y="6" width="4" height="8" rx="0.5" />
		<rect x="13.5" y="6" width="4" height="8" rx="0.5" />
	</svg>
{/snippet}

{#snippet iconLatin()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4">
		<circle cx="10" cy="10" r="8" />
		<text x="10" y="13.5" font-size="8" text-anchor="middle" fill="currentColor" stroke="none" font-family="sans-serif">A</text>
	</svg>
{/snippet}

{#snippet bucketIcon(key: string)}
	{#if key === 'garbage'}{@render iconTrash()}
	{:else if key === 'hidden'}{@render iconEye(false)}
	{:else if key === 'userWord'}{@render iconBookmark(true)}
	{:else if key === 'starred'}{@render iconStar(true)}
	{:else if key === 'extraMatch'}{@render iconPlus()}
	{:else if key === 'unrecognized'}{@render iconSequence()}
	{:else if key === 'unknown'}{@render iconQuestion()}
	{:else if key === 'dag'}{@render iconSegments()}
	{:else if key === 'nonChinese'}{@render iconLatin()}
	{/if}
{/snippet}

<!-- One chip per filter bucket - icon + label + count (always against the
     FULL unfiltered result set, see bucketCount) + at-a-glance hide/iso
     state marks. Iso-active uses a filled/highlighted treatment (blue,
     matching this app's general "selected/active" language elsewhere -
     selected familiarity score buttons, the selected-row highlight - rather
     than the star icon's amber, which is that icon's own identity color,
     not a reusable state-styling pattern). Hide-active uses a strikethrough
     label + a small dot, both visible without opening the popover. Clicking
     the chip opens a popover with two independent Hide/Isolate toggles;
     changes apply live, same as the old checkboxes did. -->
{#snippet filterChip(bucket: Bucket)}
	{@const state = bucketState[bucket.id]}
	{@const count = bucketCount(bucket)}
	<div class="relative inline-block">
		<button
			onclick={() => toggleBucketPopover(bucket.id)}
			class="flex items-center gap-1.5 pl-2 pr-2.5 py-1.5 rounded-full text-sm border transition-colors
			{state.iso ? 'bg-blue-100 border-blue-300 text-blue-700' : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'}
			{state.hide ? 'opacity-60' : ''}"
			title="{bucket.label}: {state.hide ? 'hidden' : 'shown'}{state.iso ? ', isolated' : ''} — click for options"
		>
			{@render bucketIcon(bucket.iconKey)}
			<span class={state.hide ? 'line-through' : ''}>{bucket.label}</span>
			<span class="text-xs {state.iso ? 'text-blue-500' : 'text-gray-400'}">({count})</span>
			{#if state.hide}
				<span class="w-1.5 h-1.5 rounded-full bg-red-400" aria-hidden="true"></span>
			{/if}
		</button>
		{#if openBucketPopoverFor === bucket.id}
			<div class="fixed inset-0 z-40" onclick={() => openBucketPopoverFor = null} role="presentation"></div>
			<div
				class="absolute left-0 top-full mt-1 z-50 w-44 bg-white rounded-lg shadow-lg border border-gray-100 p-3 space-y-2.5"
				onclick={(e) => e.stopPropagation()}
				role="presentation"
			>
				<label class="flex items-center justify-between text-sm text-gray-700 cursor-pointer">
					Hide
					<input
						type="checkbox"
						checked={state.hide}
						onchange={() => setBucketHide(bucket.id, !state.hide)}
						class="rounded"
					/>
				</label>
				<label class="flex items-center justify-between text-sm text-gray-700 cursor-pointer">
					Isolate
					<input
						type="checkbox"
						checked={state.iso}
						onchange={() => setBucketIso(bucket.id, !state.iso)}
						class="rounded"
					/>
				</label>
			</div>
		{/if}
	</div>
{/snippet}

<!-- Visibility quick-action, reused by both the desktop table row and the
     mobile card. Icon reflects resolved is_hidden; the corner badge shows
     hidden_governing_scope (omitted entirely when "default" - see
     scopeBadge above). Click opens a menu built by buildVisibilityMenu,
     lazily fetching+caching that word's raw scope rows on first open (see
     toggleVisibilityMenu). -->
{#snippet visibilityAction(result: WordResult)}
	<div class="relative inline-block">
		<button
			onclick={(e) => { e.stopPropagation(); toggleVisibilityMenu(result.word); }}
			class="p-1.5 rounded {result.is_hidden ? 'text-slate-600' : 'text-gray-400'} hover:text-blue-600 hover:bg-blue-50"
			title={result.is_hidden ? 'Hidden — click for options' : 'Shown — click for options'}
			aria-label="Visibility options"
		>
			{@render iconEye(!result.is_hidden)}
		</button>
		{@render scopeBadge(result.hidden_governing_scope)}
		{#if visibilityMenuOpenFor === result.word}
			<div class="fixed inset-0 z-40" onclick={() => visibilityMenuOpenFor = null} role="presentation"></div>
			<div
				class="absolute right-0 top-full mt-1 z-50 w-56 bg-white rounded-lg shadow-lg border border-gray-100 py-1"
				onclick={(e) => e.stopPropagation()}
				role="presentation"
			>
				{#if loadingVisibilityFor.has(result.word)}
					<p class="text-xs text-gray-400 px-3 py-2">Loading...</p>
				{:else}
					{#each buildVisibilityMenu(result.is_hidden, visibilityRowsByWord[result.word] ?? []) as action}
						<button
							onclick={() => applyVisibilityAction(result.word, action)}
							disabled={togglingVisibilityAction === result.word}
							class="w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50 {action.kind === 'remove' ? 'text-red-500' : 'text-gray-700'}"
						>
							{action.label}
						</button>
					{/each}
				{/if}
			</div>
		{/if}
	</div>
{/snippet}

<div class="min-h-screen bg-gray-50">
	<nav class="bg-white shadow-sm px-6 py-4 flex justify-between items-center">
		<div class="flex items-center gap-4">
			<a href="/" class="text-gray-600 hover:text-gray-800 text-sm">← Back</a>
			<h1 class="text-xl font-bold text-gray-800">
				{analysis?.title ?? 'Analysis Results'}
			</h1>
			{#if analysis}
				<a
					href="/input-texts/{analysis.input_text_id}"
					class="text-sm text-blue-600 hover:text-blue-800"
				>
					View source text
				</a>
			{/if}
		</div>
		{#if analysis}
			<div class="text-sm text-gray-500 flex gap-4">
				<span>{analysis.unique_words} unique words</span>
				<span>{analysis.total_words} total occurrences</span>
			</div>
		{/if}
	</nav>

	<main class="max-w-5xl lg:max-w-6xl 2xl:max-w-7xl mx-auto px-6 py-8">
		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		<!-- Filters -->
		<div class="bg-white rounded-lg shadow-sm p-4 mb-4 flex flex-wrap gap-4 items-center">
			<div class="flex items-center gap-2">
				<input
					type="search"
					bind:value={searchQuery}
					placeholder="Search words..."
					class="border border-gray-300 rounded px-2 py-1 text-sm w-40"
				/>
				{#if searchQuery.trim()}
					<select
						bind:value={searchScope}
						class="border border-gray-300 rounded px-2 py-1 text-sm"
						title="Search within the filters below, or across every result regardless of them"
					>
						<option value="filtered">In filtered results</option>
						<option value="all">In all results</option>
					</select>
				{/if}
			</div>

			<!-- Filter bucket chip bar - order matches the review workflow:
			     Garbage, Hidden, User words, Extra matches, Unrecognized,
			     Unknown, DAG words, Starred, Non-Chinese (see BUCKETS above). -->
			<div class="flex flex-wrap gap-1.5 items-center">
				{#each BUCKETS as bucket}
					{@render filterChip(bucket)}
				{/each}
			</div>

			<div class="flex items-center gap-2 text-sm text-gray-700">
				<span>Hide familiarity ≥</span>
				<select
					bind:value={minFamiliarityFilter}
					class="border border-gray-300 rounded px-2 py-1 text-sm"
				>
					<option value={1}>1</option>
					<option value={2}>2</option>
					<option value={3}>3</option>
					<option value={4}>4</option>
					<option value={5}>5</option>
					<option value={6}>Show all</option>
				</select>
			</div>

			<!-- Sort control - the desktop table's column headers (sortHeader
			     snippet) set this same sortColumn/sortDirection state, but the
			     mobile card list has no headers to click, so this dropdown is
			     the only way to sort there. Word sorts by raw codepoint, not
			     pinyin - see compareResults' comment. -->
			<div class="flex items-center gap-2 text-sm text-gray-700">
				<span>Sort by</span>
				<select
					value={sortColumn ?? ''}
					onchange={(e) => {
						const v = e.currentTarget.value as SortColumn | '';
						if (!v) {
							sortColumn = null;
						} else {
							sortColumn = v;
							sortDirection = 'asc';
						}
					}}
					class="border border-gray-300 rounded px-2 py-1 text-sm"
				>
					<option value="">Default</option>
					<option value="word">Word</option>
					<option value="count">Count</option>
					<option value="source">Source</option>
					<option value="familiarity">Familiarity</option>
				</select>
				{#if sortColumn}
					<button
						onclick={() => sortDirection = sortDirection === 'asc' ? 'desc' : 'asc'}
						class="p-1 rounded text-gray-500 hover:text-blue-600 hover:bg-blue-50"
						title="Toggle sort direction"
						aria-label="Toggle sort direction"
					>
						{@render iconChevron(sortDirection === 'asc')}
					</button>
				{/if}
			</div>

			<span class="text-sm text-gray-400">
				Showing {filteredResults().length} of {analysis?.results.length ?? 0} words
			</span>
		</div>

		<div class="flex flex-col sm:flex-row gap-4">
			<!-- Results table (sm and up - see the mobile card list below for < sm) -->
			<div class="hidden sm:block flex-1 min-w-0 bg-white rounded-lg shadow-sm overflow-hidden">
				{#if loading}
					<p class="text-gray-500 p-4">Loading...</p>
				{:else if analysis}
					<table class="w-full">
						<thead class="bg-gray-50 border-b border-gray-200">
							<tr>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">{@render sortHeader('Word', 'word')}</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">{@render sortHeader('Count', 'count')}</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">{@render sortHeader('Source', 'source')}</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">{@render sortHeader('Familiarity', 'familiarity')}</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Mark as</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Actions</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-gray-100">
							{#each filteredResults() as result}
								<tr
									data-word={result.word}
									onclick={(e) => handleRowClick(e, result.word)}
									class="cursor-pointer hover:bg-gray-50 {result.source === 'longest_match_only' ? 'bg-amber-50/40' : ''} {garbageWords.has(result.word) ? 'bg-red-50/40' : ''} {selectedWord?.word === result.word ? '!bg-blue-50 ring-1 ring-inset ring-blue-200' : ''}"
								>
									<td class="px-4 py-3 text-lg font-medium">
										<div class="flex items-center gap-1.5">
											<button
												onclick={() => toggleContext(result.word)}
												class="p-0.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 shrink-0"
												title="Show where this word occurs in the text"
												aria-label="Show context"
											>
												{@render iconChevron(expandedContext.has(result.word))}
											</button>
											{result.word}
										</div>
									</td>
									<td class="px-4 py-3 text-gray-600">{result.count}</td>
									<td class="px-4 py-3">
										<div class="flex flex-wrap gap-1">
											<span
												class="text-xs px-2 py-1 rounded-full {sourceColor(result.source)}"
												title={result.source === 'longest_match_only' ? 'Found only by the legacy longest-matching pass — not confirmed by the main segmenter. Likely a dictionary gap; review before trusting it.' : ''}
											>
												{sourceLabel(result.source)}
											</span>
											{#if garbageWords.has(result.word)}
												<span
													class="text-xs px-2 py-1 rounded-full bg-red-100 text-red-700"
													title="Marked as garbage — hidden by default, but kept in the results."
												>
													garbage
												</span>
											{/if}
										</div>
									</td>
									<td class="px-4 py-3">
										<span class="text-xs px-2 py-1 rounded-full {familiarityColor(currentFamiliarity(result))}">
											{familiarityLabel(currentFamiliarity(result))}
										</span>
									</td>
									<td class="px-4 py-3">
										<div class="flex flex-wrap gap-1">
											{#each [1, 2, 3, 4, 5] as score}
												<button
													onclick={() => setFamiliarity(result.word, score)}
													disabled={updatingWord === result.word}
													class="w-7 h-7 rounded text-xs font-medium disabled:opacity-50
													{currentFamiliarity(result) === score
														? 'bg-blue-600 text-white'
														: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
												>
													{score}
												</button>
											{/each}
											{#if currentFamiliarity(result) !== null}
												<button
													onclick={() => setFamiliarity(result.word, null)}
													disabled={updatingWord === result.word}
													class="w-7 h-7 rounded text-xs font-medium bg-gray-100 text-gray-400 hover:bg-gray-200 disabled:opacity-50"
												>
													✕
												</button>
											{/if}
										</div>
									</td>
									<td class="px-4 py-3">
										<div class="flex flex-wrap gap-0.5 items-center">
											<button
												onclick={() => openWordDetail(result.word)}
												class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50"
												title="View details"
												aria-label="View details"
											>
												{@render iconInfo()}
											</button>
											{@render visibilityAction(result)}
											{#if userWords.has(result.word)}
												<button
													onclick={() => removeUserWord(result.word)}
													disabled={addingUserWord === result.word}
													class="p-1.5 rounded {userWordAffectsDag[result.word] ? 'text-emerald-600' : 'text-slate-500'} hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
													title={userWordTooltip(result.word)}
													aria-label="In your dictionary — click to remove"
												>
													{@render iconBookmark(true)}
												</button>
											{:else}
												<button
													onclick={() => addUserWord(result.word)}
													disabled={addingUserWord === result.word}
													class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50"
													title="Add to your custom dictionary — helps future segmentation recognize this word"
													aria-label="Add to your custom dictionary"
												>
													{@render iconBookmark(false)}
												</button>
											{/if}
											{#if starredWords.has(result.word)}
												<button
													onclick={() => unmarkStarred(result.word)}
													disabled={togglingStarred === result.word}
													class="p-1.5 rounded text-amber-500 hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
													title="Starred — click to unstar"
													aria-label="Starred — click to unstar"
												>
													{@render iconStar(true)}
												</button>
											{:else}
												<button
													onclick={() => markAsStarred(result.word)}
													disabled={togglingStarred === result.word}
													class="p-1.5 rounded text-gray-400 hover:text-amber-500 hover:bg-amber-50 disabled:opacity-50"
													title="Star as interesting"
													aria-label="Star as interesting"
												>
													{@render iconStar(false)}
												</button>
											{/if}
											{#if garbageWords.has(result.word)}
												<button
													onclick={() => unmarkGarbage(result.word)}
													disabled={togglingGarbage === result.word}
													class="p-1.5 rounded text-red-600 hover:text-red-800 hover:bg-red-50 disabled:opacity-50"
													title="Marked as garbage — click to unmark"
													aria-label="Marked as garbage — click to unmark"
												>
													{@render iconTrash()}
												</button>
											{:else}
												<button
													onclick={() => markAsGarbage(result.word)}
													disabled={togglingGarbage === result.word}
													class="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
													title="Mark as garbage — hidden by default, but kept in the results"
													aria-label="Mark as garbage"
												>
													{@render iconTrash()}
												</button>
											{/if}
										</div>
									</td>
								</tr>
								{#if expandedContext.has(result.word)}
									<tr class="bg-gray-50">
										<td colspan="6" class="px-4 py-3 border-t border-gray-100">
											{@render contextList(result.word)}
										</td>
									</tr>
								{/if}
							{/each}
						</tbody>
					</table>
				{/if}
			</div>

			<!-- Mobile card list (< sm) - collapsed to word + two accordion
			     toggles: "+" for read-only info, hamburger for the interactive
			     controls. Independent per-word toggles (expandedInfo/expandedActions),
			     everything below reuses the exact same handlers/derived helpers
			     and icon snippets the desktop table above uses. -->
			<div class="sm:hidden bg-white rounded-lg shadow-sm overflow-hidden divide-y divide-gray-100">
				{#if loading}
					<p class="text-gray-500 p-4">Loading...</p>
				{:else if analysis}
					{#each filteredResults() as result}
						<div class="{result.source === 'longest_match_only' ? 'bg-amber-50/40' : ''} {garbageWords.has(result.word) ? 'bg-red-50/40' : ''}">
							<div class="flex items-center justify-between gap-2 px-4 py-3">
								<span class="text-lg font-medium truncate">{result.word}</span>
								<div class="flex items-center gap-0.5 shrink-0">
									<button
										onclick={() => toggleInfo(result.word)}
										class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50"
										title="Show count, source, familiarity"
										aria-label="Show details"
									>
										{@render iconPlusMinus(expandedInfo.has(result.word))}
									</button>
									<button
										onclick={() => toggleActions(result.word)}
										class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50"
										title="Show options"
										aria-label="Show options"
									>
										{@render iconHamburger(expandedActions.has(result.word))}
									</button>
								</div>
							</div>

							{#if expandedInfo.has(result.word)}
								<div class="flex flex-wrap items-center gap-2 border-t border-gray-50 px-4 pt-2 pb-3 text-sm">
									<span class="text-gray-600">Count: {result.count}</span>
									<span
										class="text-xs px-2 py-1 rounded-full {sourceColor(result.source)}"
										title={result.source === 'longest_match_only' ? 'Found only by the legacy longest-matching pass — not confirmed by the main segmenter. Likely a dictionary gap; review before trusting it.' : ''}
									>
										{sourceLabel(result.source)}
									</span>
									{#if garbageWords.has(result.word)}
										<span class="text-xs px-2 py-1 rounded-full bg-red-100 text-red-700">garbage</span>
									{/if}
									<span class="text-xs px-2 py-1 rounded-full {familiarityColor(currentFamiliarity(result))}">
										{familiarityLabel(currentFamiliarity(result))}
									</span>
								</div>
								<div class="border-t border-gray-50 px-4 pt-2 pb-3">
									<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Context</p>
									{@render contextList(result.word)}
								</div>
							{/if}

							{#if expandedActions.has(result.word)}
								<div class="space-y-2 border-t border-gray-50 px-4 pt-2 pb-3">
									<div class="flex gap-1">
										{#each [1, 2, 3, 4, 5] as score}
											<button
												onclick={() => setFamiliarity(result.word, score)}
												disabled={updatingWord === result.word}
												class="w-7 h-7 rounded text-xs font-medium disabled:opacity-50
												{currentFamiliarity(result) === score
													? 'bg-blue-600 text-white'
													: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
											>
												{score}
											</button>
										{/each}
										{#if currentFamiliarity(result) !== null}
											<button
												onclick={() => setFamiliarity(result.word, null)}
												disabled={updatingWord === result.word}
												class="w-7 h-7 rounded text-xs font-medium bg-gray-100 text-gray-400 hover:bg-gray-200 disabled:opacity-50"
											>
												✕
											</button>
										{/if}
									</div>
									<div class="flex flex-wrap items-center gap-0.5">
										<button
											onclick={() => openWordDetail(result.word)}
											class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50"
											title="View details"
											aria-label="View details"
										>
											{@render iconInfo()}
										</button>
										{@render visibilityAction(result)}
										{#if userWords.has(result.word)}
											<button
												onclick={() => removeUserWord(result.word)}
												disabled={addingUserWord === result.word}
												class="p-1.5 rounded {userWordAffectsDag[result.word] ? 'text-emerald-600' : 'text-slate-500'} hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
												title={userWordTooltip(result.word)}
												aria-label="In your dictionary — click to remove"
											>
												{@render iconBookmark(true)}
											</button>
										{:else}
											<button
												onclick={() => addUserWord(result.word)}
												disabled={addingUserWord === result.word}
												class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50"
												title="Add to your custom dictionary — helps future segmentation recognize this word"
												aria-label="Add to your custom dictionary"
											>
												{@render iconBookmark(false)}
											</button>
										{/if}
										{#if starredWords.has(result.word)}
											<button
												onclick={() => unmarkStarred(result.word)}
												disabled={togglingStarred === result.word}
												class="p-1.5 rounded text-amber-500 hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
												title="Starred — click to unstar"
												aria-label="Starred — click to unstar"
											>
												{@render iconStar(true)}
											</button>
										{:else}
											<button
												onclick={() => markAsStarred(result.word)}
												disabled={togglingStarred === result.word}
												class="p-1.5 rounded text-gray-400 hover:text-amber-500 hover:bg-amber-50 disabled:opacity-50"
												title="Star as interesting"
												aria-label="Star as interesting"
											>
												{@render iconStar(false)}
											</button>
										{/if}
										{#if garbageWords.has(result.word)}
											<button
												onclick={() => unmarkGarbage(result.word)}
												disabled={togglingGarbage === result.word}
												class="p-1.5 rounded text-red-600 hover:text-red-800 hover:bg-red-50 disabled:opacity-50"
												title="Marked as garbage — click to unmark"
												aria-label="Marked as garbage — click to unmark"
											>
												{@render iconTrash()}
											</button>
										{:else}
											<button
												onclick={() => markAsGarbage(result.word)}
												disabled={togglingGarbage === result.word}
												class="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
												title="Mark as garbage — hidden by default, but kept in the results"
												aria-label="Mark as garbage"
											>
												{@render iconTrash()}
											</button>
										{/if}
									</div>
								</div>
							{/if}
						</div>
					{/each}
				{/if}
			</div>

			<!-- Word detail panel - below `lg`, this is a fixed bottom-sheet
			     overlay (with a dismiss backdrop) instead of a block in normal
			     document flow. Two separate reasons this needs to stay an
			     overlay all the way up to `lg`, not just on mobile: below
			     `sm` the card list above it can be very long, so a
			     normal-flow panel would render off-screen at the bottom,
			     invisible until scrolled all the way down; between `sm` and
			     `lg`, the desktop *table* is already showing (it only needs
			     ~640px to look fine on its own), but a table narrow enough to
			     fit there has no room left to also fit a 288px side panel
			     next to it without squeezing "Mark as"/"Actions" into
			     unreadable overlap - so the panel keeps overlaying instead of
			     joining the flex row until there's actually room (`lg`,
			     1024px) for both side by side. lg:contents removes the
			     backdrop wrapper's own box once that's true, so it doesn't
			     affect the side-by-side layout there. -->
			{#if selectedWord || loadingDetail}
				<div
					class="fixed inset-0 z-40 flex items-end justify-center bg-black/30 lg:contents"
					onclick={() => selectedWord = null}
					role="presentation"
				>
				<div
					class="w-full lg:w-72 max-h-[85vh] overflow-y-auto bg-white rounded-t-2xl lg:rounded-lg shadow-sm p-4 self-start lg:sticky lg:top-4"
					onclick={(e) => e.stopPropagation()}
					role="presentation"
				>
					{#if loadingDetail}
						<p class="text-gray-500 text-sm">Loading...</p>
					{:else if selectedWord}
						{@const word = selectedWord.word}
					{@const uwCols = resolveScopeColumns(userWordScope, id, analysis?.input_text_id)}
					{@const uwEntryAtScope = selectedWord.user_words.find((e) => columnsMatch(e, uwCols))}
						<div class="flex justify-between items-start mb-3">
							<h2 class="text-3xl font-medium">{selectedWord.word}</h2>
							<button
								onclick={() => selectedWord = null}
								class="text-gray-400 hover:text-gray-600"
							>✕</button>
						</div>

						<!-- Familiarity + actions - everything available from the row
						     is also available here, so the panel is a complete
						     substitute rather than needing a trip back to the row.
						     Familiarity is always global (no scope selector here -
						     see KnownWord's docstring, models.py); the Bookmark quick
						     action below uses userWordScope, set independently in its
						     own section further down. -->
						<div class="border-b border-gray-100 mb-4 pb-4">
							<div class="flex flex-wrap gap-1 mb-2">
								{#each [1, 2, 3, 4, 5] as score}
									<button
										onclick={() => setFamiliarity(word, score)}
										disabled={updatingWord === word}
										class="w-8 h-8 rounded text-xs font-medium disabled:opacity-50
										{(knownWords[word] ?? null) === score
											? 'bg-blue-600 text-white'
											: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
									>
										{score}
									</button>
								{/each}
								{#if (knownWords[word] ?? null) !== null}
									<button
										onclick={() => setFamiliarity(word, null)}
										disabled={updatingWord === word}
										class="w-8 h-8 rounded text-xs font-medium bg-gray-100 text-gray-400 hover:bg-gray-200 disabled:opacity-50"
									>
										✕
									</button>
								{/if}
							</div>
							<div class="flex flex-wrap items-center gap-0.5">
								{#if uwEntryAtScope}
									<button
										onclick={() => removeUserWord(word, uwEntryAtScope.scope_analysis_id, uwEntryAtScope.scope_input_text_id)}
										disabled={addingUserWord === word}
										class="p-1.5 rounded {uwEntryAtScope.affects_dag ? 'text-emerald-600' : 'text-slate-500'} hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
										title={uwEntryAtScope.affects_dag === false ? 'In your dictionary at this scope, excluded from segmentation — click to remove' : uwEntryAtScope.affects_dag === null ? 'In your dictionary at this scope, no segmentation preference set — click to remove' : 'In your dictionary at this scope — click to remove'}
										aria-label="In your dictionary at this scope — click to remove"
									>
										{@render iconBookmark(true)}
									</button>
								{:else}
									<button
										onclick={() => addUserWord(word, { analysisId: id, inputTextId: analysis?.input_text_id, scope: userWordScope })}
										disabled={addingUserWord === word}
										class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50"
										title="Add to your custom dictionary at this scope — helps future segmentation recognize this word"
										aria-label="Add to your custom dictionary"
									>
										{@render iconBookmark(false)}
									</button>
								{/if}
								{#if starredWords.has(word)}
									<button
										onclick={() => unmarkStarred(word)}
										disabled={togglingStarred === word}
										class="p-1.5 rounded text-amber-500 hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
										title="Starred — click to unstar"
										aria-label="Starred — click to unstar"
									>
										{@render iconStar(true)}
									</button>
								{:else}
									<button
										onclick={() => markAsStarred(word)}
										disabled={togglingStarred === word}
										class="p-1.5 rounded text-gray-400 hover:text-amber-500 hover:bg-amber-50 disabled:opacity-50"
										title="Star as interesting"
										aria-label="Star as interesting"
									>
										{@render iconStar(false)}
									</button>
								{/if}
								{#if garbageWords.has(word)}
									<button
										onclick={() => unmarkGarbage(word)}
										disabled={togglingGarbage === word}
										class="p-1.5 rounded text-red-600 hover:text-red-800 hover:bg-red-50 disabled:opacity-50"
										title="Marked as garbage — click to unmark"
										aria-label="Marked as garbage — click to unmark"
									>
										{@render iconTrash()}
									</button>
								{:else}
									<button
										onclick={() => markAsGarbage(word)}
										disabled={togglingGarbage === word}
										class="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-50"
										title="Mark as garbage — hidden by default, but kept in the results"
										aria-label="Mark as garbage"
									>
										{@render iconTrash()}
									</button>
								{/if}
							</div>
						</div>

						<!-- Corpus frequency -->
						<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Corpus frequency</p>
						{#if selectedWord.frequency}
							<p class="text-sm text-gray-700">{selectedWord.frequency.toLocaleString()}</p>
						{:else}
							<p class="text-sm text-gray-400">No frequency data for this word.</p>
						{/if}

						<!-- HSK -->
						<div class="border-t border-gray-100 mt-4 pt-3">
							<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">HSK</p>

							{#if selectedWord.hsk_v2_2012 || selectedWord.hsk_v3_2021 || selectedWord.hsk_v3_2026 || selectedWord.forms.length > 0}
								<div class="flex flex-wrap gap-1 mb-3">
									{#if selectedWord.hsk_v2_2012}
										<span class="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded-full">
											HSK 2012: {selectedWord.hsk_v2_2012}
										</span>
									{/if}
									{#if selectedWord.hsk_v3_2021}
										<span class="text-xs px-2 py-1 bg-purple-100 text-purple-700 rounded-full">
											HSK 2021: {selectedWord.hsk_v3_2021}
										</span>
									{/if}
									{#if selectedWord.hsk_v3_2026}
										<span class="text-xs px-2 py-1 bg-green-100 text-green-700 rounded-full">
											HSK 2026: {selectedWord.hsk_v3_2026}
										</span>
									{/if}
								</div>

								{#if selectedWord.forms.length > 0}
									<div class="space-y-3">
										{#each selectedWord.forms as form, i}
											<div class="{i > 0 ? 'border-t border-gray-100 pt-3' : ''}">
												{#if selectedWord.forms.length > 1}
													<p class="text-xs text-gray-400 mb-1">Form {i + 1}</p>
												{/if}
												{#if form.traditional && form.traditional !== selectedWord.word}
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
													<p class="text-xs text-gray-500 mt-1">
														Classifiers: {form.classifiers.join(', ')}
													</p>
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

							{#if selectedWord.cedict.length > 0}
								<div class="space-y-3">
									{#each selectedWord.cedict as sense, i}
										<div class="{i > 0 ? 'border-t border-gray-100 pt-3' : ''}">
											{#if selectedWord.cedict.length > 1}
												<p class="text-xs text-gray-400 mb-1">Sense {i + 1}</p>
											{/if}
											{#if sense.traditional && sense.traditional !== selectedWord.word}
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

						<!-- Your entries - one per scope this word actually has an entry
						     at (up to 3: global/this text/this analysis), most specific
						     first, never resolved to one - see WordDetail.user_words'
						     docstring (schemas.py). Each is independently editable/
						     deletable; no entry ever implies or hides another. -->
						<div class="border-t border-gray-100 mt-4 pt-3">
							<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Your entries</p>

							{#each selectedWord.user_words as entry (entry.id)}
								{@const editing = entryEditingIds.has(entry.id)}
								<div class="mb-2 pb-2 border-b border-gray-50 last:border-0">
									<div class="flex justify-between items-center mb-1">
										<span class="text-xs font-medium text-gray-500">{scopeLabel(entry)}</span>
										<div class="flex gap-2">
											{#if !editing}
												<button
													onclick={() => startEditingEntry(entry)}
													class="text-xs text-blue-600 hover:text-blue-800"
												>
													Edit
												</button>
											{/if}
											<button
												onclick={() => deleteEntry(entry)}
												disabled={savingEntryId === entry.id}
												class="text-xs text-red-400 hover:text-red-600 disabled:opacity-50"
											>
												Delete
											</button>
										</div>
									</div>

									{#if editing}
										<div class="space-y-2">
											<div>
												<label for="uw-pronunciation-{entry.id}" class="text-xs text-gray-500">Pronunciation</label>
												<input
													id="uw-pronunciation-{entry.id}"
													type="text"
													bind:value={entryDrafts[entry.id].pronunciation}
													placeholder="e.g. dà yě láng"
													class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
												/>
											</div>
											<div>
												<label for="uw-meaning-{entry.id}" class="text-xs text-gray-500">
													Meaning / definition
													<span class="text-gray-400 font-normal">- separate senses with "/", CC-CEDICT style</span>
												</label>
												<textarea
													id="uw-meaning-{entry.id}"
													bind:value={entryDrafts[entry.id].meaning}
													placeholder="to run/to flee/(of a horse) to gallop"
													rows="2"
													class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
												></textarea>
											</div>
											<div>
												<label for="uw-notes-{entry.id}" class="text-xs text-gray-500">Notes</label>
												<textarea
													id="uw-notes-{entry.id}"
													bind:value={entryDrafts[entry.id].notes}
													placeholder="Any other notes — context, mnemonics, etc."
													rows="2"
													class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
												></textarea>
											</div>
											{#if entry.scope_analysis_id == null}
												<!-- Hidden at analysis scope - an analysis-scoped
												     affects_dag can never have an observable effect
												     (build_user_overlay never resolves analysis-scoped
												     rows, since the analysis it's scoped to has already
												     finished segmenting by the time such a row could
												     exist) - see UserWord's docstring (models.py).
												     Tri-state, not a checkbox - NULL ("no preference")
												     is a real, distinct value from false ("excluded"),
												     not just "unchecked" - see affects_dag's docstring. -->
												<div class="text-xs text-gray-500">
													<span class="block mb-1">Segmentation weight</span>
													<label class="flex items-center gap-1.5 mb-0.5">
														<input
															type="radio"
															name="affects-dag-{entry.id}"
															checked={entryDrafts[entry.id].affectsDag === true}
															onchange={() => entryDrafts[entry.id].affectsDag = true}
														/>
														Affects segmentation
													</label>
													<label class="flex items-center gap-1.5 mb-0.5">
														<input
															type="radio"
															name="affects-dag-{entry.id}"
															checked={entryDrafts[entry.id].affectsDag === false}
															onchange={() => entryDrafts[entry.id].affectsDag = false}
														/>
														Excluded from segmentation
													</label>
													<label class="flex items-center gap-1.5">
														<input
															type="radio"
															name="affects-dag-{entry.id}"
															checked={entryDrafts[entry.id].affectsDag === null}
															onchange={() => entryDrafts[entry.id].affectsDag = null}
														/>
														No preference (inherit from broader scope)
													</label>
												</div>
											{/if}
											<div class="flex gap-2 pt-1">
												<button
													onclick={() => saveEntry(entry)}
													disabled={savingEntryId === entry.id}
													class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
												>
													{savingEntryId === entry.id ? 'Saving...' : 'Save'}
												</button>
												<button
													onclick={() => cancelEditingEntry(entry.id)}
													disabled={savingEntryId === entry.id}
													class="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700"
												>
													Cancel
												</button>
											</div>
										</div>
									{:else}
										<div class="space-y-1">
											{#if entry.pronunciation}
												<p class="text-sm text-blue-600">{entry.pronunciation}</p>
											{/if}
											{#if entry.meaning}
												<p class="text-sm text-gray-700">{entry.meaning}</p>
											{/if}
											{#if entry.notes}
												<p class="text-xs text-gray-500 italic">{entry.notes}</p>
											{/if}
											{#if !entry.pronunciation && !entry.meaning && !entry.notes}
												<p class="text-sm text-gray-400">No details added yet.</p>
											{/if}
											{#if entry.scope_analysis_id == null && entry.affects_dag === false}
												<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">Excluded from segmentation</span>
											{:else if entry.scope_analysis_id == null && entry.affects_dag === null}
												<span class="inline-block text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-400">No segmentation preference (inherits)</span>
											{/if}
										</div>
									{/if}
								</div>
							{/each}

							{#if selectedWord.user_words.length === 0}
								<p class="text-sm text-gray-400 mb-2">Not in your dictionary at any scope.</p>
							{/if}

							{#if missingScopes(selectedWord.user_words).length > 0}
								{#if addingNewEntry}
									<div class="space-y-2 mt-1">
										<div>
											<label for="uw-new-pronunciation" class="text-xs text-gray-500">Pronunciation</label>
											<input
												id="uw-new-pronunciation"
												type="text"
												bind:value={newEntryDraft.pronunciation}
												placeholder="e.g. dà yě láng"
												class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
											/>
										</div>
										<div>
											<label for="uw-new-meaning" class="text-xs text-gray-500">
												Meaning / definition
												<span class="text-gray-400 font-normal">- separate senses with "/", CC-CEDICT style</span>
											</label>
											<textarea
												id="uw-new-meaning"
												bind:value={newEntryDraft.meaning}
												placeholder="to run/to flee/(of a horse) to gallop"
												rows="2"
												class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
											></textarea>
										</div>
										<div>
											<label for="uw-new-notes" class="text-xs text-gray-500">Notes</label>
											<textarea
												id="uw-new-notes"
												bind:value={newEntryDraft.notes}
												placeholder="Any other notes — context, mnemonics, etc."
												rows="2"
												class="w-full border border-gray-300 rounded px-2 py-1 text-sm mt-0.5"
											></textarea>
										</div>
										{#if userWordScope !== 'analysis'}
											<!-- Hidden at analysis scope, tri-state not a checkbox -
											     see the matching note on the per-entry edit form above. -->
											<div class="text-xs text-gray-500">
												<span class="block mb-1">Segmentation weight</span>
												<label class="flex items-center gap-1.5 mb-0.5">
													<input
														type="radio"
														name="affects-dag-new"
														checked={newEntryDraft.affectsDag === true}
														onchange={() => newEntryDraft.affectsDag = true}
													/>
													Affects segmentation
												</label>
												<label class="flex items-center gap-1.5 mb-0.5">
													<input
														type="radio"
														name="affects-dag-new"
														checked={newEntryDraft.affectsDag === false}
														onchange={() => newEntryDraft.affectsDag = false}
													/>
													Excluded from segmentation
												</label>
												<label class="flex items-center gap-1.5">
													<input
														type="radio"
														name="affects-dag-new"
														checked={newEntryDraft.affectsDag === null}
														onchange={() => newEntryDraft.affectsDag = null}
													/>
													No preference (inherit from broader scope)
												</label>
											</div>
										{/if}
										<div class="flex gap-2 pt-1">
											<button
												onclick={saveNewEntry}
												disabled={savingEntryId === -1}
												class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
											>
												{savingEntryId === -1 ? 'Saving...' : 'Save'}
											</button>
											<button
												onclick={() => addingNewEntry = false}
												disabled={savingEntryId === -1}
												class="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700"
											>
												Cancel
											</button>
										</div>
									</div>
								{:else}
									<label class="flex items-center gap-1.5 text-xs text-gray-500 mt-1">
										Add entry at
										<select
											bind:value={userWordScope}
											class="border border-gray-300 rounded px-1.5 py-0.5 text-xs"
											title="Which scope a new dictionary entry for this word is saved at"
										>
											{#each missingScopes(selectedWord.user_words) as s}
												<option value={s.value}>{s.label}</option>
											{/each}
										</select>
									</label>
									<button
										onclick={startAddingNewEntry}
										class="text-xs text-blue-600 hover:text-blue-800 mt-1"
									>
										+ Add entry
									</button>
								{/if}
							{/if}
						</div>

						<!-- Sample sentences - a word can have many, independent of
						     whether it's in "Your entry" above (see SampleSentence's
						     docstring, models.py) - copy the relevant part from a
						     context occurrence (row/card chevron or "+" accordion)
						     and paste it in here. -->
						<div class="border-t border-gray-100 mt-4 pt-3">
							<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Sample sentences</p>

							{#if selectedWord.sample_sentences.length}
								<ul class="space-y-1.5 mb-2">
									{#each selectedWord.sample_sentences as s (s.id)}
										<li class="flex items-start justify-between gap-2">
											<p class="text-sm text-gray-700">{s.sentence}</p>
											<button
												onclick={() => removeSampleSentence(s.id)}
												disabled={deletingSentenceId === s.id}
												class="text-gray-300 hover:text-red-600 disabled:opacity-50 shrink-0"
												title="Remove sample sentence"
												aria-label="Remove sample sentence"
											>✕</button>
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
								<button
									onclick={addSampleSentence}
									disabled={!newSentenceDraft.trim() || savingSentence}
									class="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 shrink-0"
								>
									{savingSentence ? '...' : 'Add'}
								</button>
							</div>
						</div>

						<!-- Visibility ("hide from results") - reuses the same
						     multi-entry-per-scope display pattern as "Your entries"
						     above (see that section's comment), but unlike
						     affects_dag, ALL THREE scope slots are shown/editable
						     here, including analysis: an analysis-scoped affects_dag
						     can never have an observable effect (the analysis has
						     already finished segmenting by the time such a row
						     could exist), but an analysis-scoped hidden override
						     DOES have a real, observable effect every time that
						     exact analysis is reopened and re-rendered - see
						     WordVisibility's docstring (models.py). Placed last in
						     the panel (below Sample sentences) - deliberate, not
						     grouped with the other dictionary-ish sections above. -->
						<div class="border-t border-gray-100 mt-4 pt-3">
							<p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Visibility</p>
							<p class="text-sm text-gray-700 mb-2">{visibilitySummary(selectedWord.word_visibility)}</p>

							{#each ALL_SCOPES as s}
								{@const entry = visibilityEntryAtScope(s.value)}
								<div class="flex items-center justify-between gap-2 py-1">
									<span class="text-xs text-gray-500">{s.label}</span>
									{#if entry}
										<div class="flex items-center gap-2">
											<button
												onclick={() => setVisibility(s.value, !entry.hidden)}
												disabled={togglingVisibilityScope === s.value}
												class="text-xs px-2 py-1 rounded-full disabled:opacity-50 {entry.hidden ? 'bg-slate-200 text-slate-700' : 'bg-emerald-100 text-emerald-700'}"
											>
												{entry.hidden ? 'Hidden' : 'Shown'}
											</button>
											<button
												onclick={() => removeVisibilityOverride(s.value)}
												disabled={togglingVisibilityScope === s.value}
												class="text-xs text-red-400 hover:text-red-600 disabled:opacity-50"
											>
												Remove override
											</button>
										</div>
									{:else if addingVisibilityOverrideFor === s.value}
										<div class="flex items-center gap-1">
											<button
												onclick={() => setVisibility(s.value, false)}
												disabled={togglingVisibilityScope === s.value}
												class="text-xs px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 hover:bg-emerald-200 disabled:opacity-50"
											>
												Shown
											</button>
											<button
												onclick={() => setVisibility(s.value, true)}
												disabled={togglingVisibilityScope === s.value}
												class="text-xs px-2 py-1 rounded-full bg-slate-200 text-slate-700 hover:bg-slate-300 disabled:opacity-50"
											>
												Hidden
											</button>
											<button
												onclick={() => addingVisibilityOverrideFor = null}
												class="text-xs text-gray-400 hover:text-gray-600"
											>
												Cancel
											</button>
										</div>
									{:else}
										<div class="flex items-center gap-2">
											<span class="text-xs text-gray-400">Not set - inherits from broader scope</span>
											<button
												onclick={() => addingVisibilityOverrideFor = s.value}
												class="text-xs text-blue-600 hover:text-blue-800"
											>
												+ Override
											</button>
										</div>
									{/if}
								</div>
							{/each}
						</div>

					{/if}
				</div>
				</div>
			{/if}
		</div>
	</main>
</div>