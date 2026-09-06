<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import type { Scope } from '$lib/api';
	import { familiarityLabel, familiarityColor, evidenceTierLabel, evidenceTierColor, bucketLabel, bucketColor } from '$lib/wordDisplay';
	import { goto } from '$app/navigation';
	import type { PageProps } from './$types';
	import WordDetailModal from '$lib/components/WordDetailModal.svelte';
	import ReadingView from '$lib/components/ReadingView.svelte';
	import { isEntryEditable, type WordDetailContext } from '$lib/wordDetailContext';

	let { params }: PageProps = $props();

	// Filter preferences persist across reloads as a global per-browser
	// setting (not per-analysis) - "always resets to hide >= 4" was the
	// complaint being fixed. Search text itself is deliberately NOT
	// persisted - a stale search term left over from a previous analysis
	// would just be confusing on a new one.
	const FILTER_STORAGE_KEY = 'mandarin_tools_analysis_filters';

	// Per-bucket state, keyed by bucket id (see BUCKETS below) - a chip is in
	// exactly one of these three at a time, cycling show -> iso -> hide ->
	// show on click. Replaces the old independent {hide, iso} booleans, which
	// allowed a chip to be both hidden AND isolated at once - isolate
	// restricts the table to matching rows, then hide removes those same
	// rows, so that combination silently blanked the whole table. A single
	// tri-state value makes it unreachable by construction.
	type BucketFilterState = 'show' | 'iso' | 'hide';

	interface StoredFilters {
		buckets: Record<string, BucketFilterState>;
		minFamiliarityFilter: number;
		searchScope: 'filtered' | 'all';
		// See SortColumn's declaration further down - referencing it here is
		// fine, TS type positions aren't subject to the declaration-order
		// rules runtime `let`/`const` bindings are.
		sortColumn: SortColumn;
		sortDirection: 'asc' | 'desc';
		filtersOpen: boolean;
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

	// Reads one bucket's stored value, tolerating the pre-tri-state
	// {hide, iso} object shape from a returning user's localStorage. Falls
	// back to the bucket's own default when nothing usable is stored.
	function resolveStoredBucketState(raw: unknown, defaultHide: boolean): BucketFilterState {
		if (raw === 'show' || raw === 'iso' || raw === 'hide') return raw;
		if (raw && typeof raw === 'object') {
			const legacy = raw as { hide?: boolean; iso?: boolean };
			if (legacy.iso) return 'iso';
			if (legacy.hide) return 'hide';
			return 'show';
		}
		return defaultHide ? 'hide' : 'show';
	}

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
		// to this viewing context (see backend's _resolve_user_word_detail,
		// router.py). Equivalent to userword_scopes.length > 0 - kept as its
		// own field since it's what the "User words" filter bucket tests.
		is_user_word: boolean;
		// Which of "global"/"text"/"analysis" currently have a UserWord row
		// for this word, canonical order, 0-3 entries - UserWord entries
		// coexist rather than cascading (see UserWord's docstring, models.py),
		// so this can't collapse to a single governing scope the way
		// hidden_governing_scope does. Drives the results-table quick-
		// action's badge fan (see userWordScopeBadges).
		userword_scopes: string[];
		// The winning entry's affects_dag, resolved analysis > text > global
		// (skipping a NULL opinion, falling back to true if nothing
		// resolves) - see _resolve_user_word_detail's docstring (router.py).
		// Already collapsed to plain true/false. Not used for the quick-
		// action icon's own color (that's neutral, existence-only, like
		// visibilityAction's) - the per-scope badges carry the color
		// instead, from userword_scope_affects_dag below.
		userword_resolved_affects_dag: boolean;
		// Each scope-in-userword_scopes' OWN raw affects_dag (tri-state,
		// unresolved/uninherited) - e.g. {global: true, text: null}. Drives
		// each badge in the fan showing ITS OWN scope's setting, rather
		// than every badge showing the one resolved winner's.
		userword_scope_affects_dag: Record<string, boolean | null>;
		// Resolved (never persisted) same as is_garbage/is_hidden - a second,
		// orthogonal dimension from `source`: `source` is which pipeline
		// pass produced this row (still backs BUCKETS and the
		// longest_match_only warning below, unchanged); `evidence_tier` is
		// why a user should trust this as a real word (User > Dictionary >
		// Corpus > Unknown - see WordResult.evidence_tier's docstring,
		// schemas.py). This is what the per-row chip now shows.
		evidence_tier: 'user' | 'dictionary' | 'corpus' | 'unknown';
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

	// Trimmed to just what the row/card quick-action popovers still need
	// (via toggleVisibilityMenu/toggleUserWordMenu below) - the full
	// WordDetail response has more fields (Dictionary/HSK/CC-CEDICT/sample
	// sentences/the new flat user_word_entries/visibility_entries), but
	// this page no longer reads any of those directly - WordDetailPanel.svelte
	// fetches and owns all of that itself now.
	interface WordDetail {
		word: string;
		// Every UserWord entry across the relevant scope levels, most
		// specific first - never resolved to one, see backend's WordDetail
		// docstring (schemas.py).
		user_words: UserWordDetail[];
		// Same multi-entry, most-specific-first shape as user_words, for the
		// Visibility section - see WordVisibility's docstring (models.py).
		word_visibility: WordVisibilityEntry[];
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
	let starredWords = $state(new Set<string>());
	let togglingStarred = $state('');
	// Visibility ("hide from results") - visibilityRowsByWord caches the up
	// -to-3 raw WordVisibility rows per word, fetched lazily the first time
	// that word's quick-action menu is opened (same lazy+cache pattern as
	// contextByWord below), used to build the menu (see buildVisibilityMenu)
	// and kept in sync with WordDetailPanel.svelte's own entries via
	// handleVisibilityEntriesChanged
	// when either mutates.
	let visibilityRowsByWord: Record<string, WordVisibilityEntry[]> = $state({});
	let loadingVisibilityFor = $state(new Set<string>());
	let visibilityMenuOpenFor: string | null = $state(null);
	let togglingVisibilityAction: string | null = $state(null);
	// UserWord quick-action - same lazy+cache pattern as visibilityRowsByWord
	// above, for the exact same reason (the results-table menu needs the raw
	// up-to-3 scoped rows to build its per-scope summary/add/remove actions,
	// not just the resolved userword_scopes/userword_resolved_affects_dag on
	// WordResult). Kept in sync with WordDetailPanel.svelte's own entries via
	// handleUserWordEntriesChanged
	// when either mutates - see addUserWord/removeUserWord/saveEntry/
	// deleteEntry/saveNewEntry.
	let userWordRowsByWord: Record<string, UserWordDetail[]> = $state({});
	let loadingUserWordFor = $state(new Set<string>());
	let userWordMenuOpenFor: string | null = $state(null);
	let togglingUserWordAction: string | null = $state(null);
	// Mobile card list only - independent per-row accordion toggles (see
	// snippets iconPlusMinus/iconHamburger and the min-[700px]:hidden card block).
	let expandedInfo = $state(new Set<string>());
	let expandedActions = $state(new Set<string>());
	// The word currently shown in WordDetailPanel.svelte, or null when
	// closed - the component owns all of its own fetching/editing state
	// internally now, this page just tracks which word (if any) to show it
	// for and reacts to its change-callbacks (see handleUserWordEntriesChanged/
	// handleVisibilityEntriesChanged below) to keep the row/card quick-
	// action icons in sync.
	let selectedWordForPanel: string | null = $state(null);
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

	const id = $derived(parseInt(params.id));

	// This page's viewing context, for WordDetailPanel.svelte - analysis
	// context (carries textId too, since an analysis belongs to a specific
	// text - see isEntryEditable's docstring, wordDetailContext.ts) once the
	// analysis has loaded, global beforehand (there's nothing more specific
	// to offer yet).
	const panelContext: WordDetailContext = $derived.by(() => {
		if (!analysis) return { type: 'global' };
		return { type: 'analysis', textId: analysis.input_text_id, textTitle: analysis.title, analysisId: id, analysisTitle: analysis.title };
	});

	// Read-only reading view (ReadingView.svelte) - a completely separate
	// mode from the filter bar/results table/mobile card list below, not
	// shown alongside them (both would otherwise want their own
	// WordDetailPanel instance for the same word at once). Defaults off -
	// fetching GET /analyze/{id}/spans is opt-in cost, and the reading view
	// itself shouldn't clutter the page for a user who never asks for it.
	let readingViewOn = $state(false);

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
		swatchColor: string;
		test: (r: WordResult) => boolean;
		defaultHide: boolean;
		group: 'bucket' | 'tier' | 'other';
	}

	const BUCKETS: Bucket[] = [
		// --- Bucket axis: which pass produced this row. Every word falls into
		// exactly one of these three - see bucketLabel/bucketColor
		// (wordDisplay.ts) for the legacy-value folding (trie/longest_match_only/
		// token from before the segmentation-engine rework).
		{ id: 'mainSegmentation', label: 'Main segmentation', swatchColor: 'bg-blue-500', group: 'bucket', test: (r) => r.source === 'dag' || r.source === 'overlay' || r.source === 'unknown' || r.source === 'trie', defaultHide: false },
		{ id: 'extraMatch', label: 'Extra matches', swatchColor: 'bg-amber-500', group: 'bucket', test: (r) => r.source === 'extra_match' || r.source === 'longest_match_only', defaultHide: false },
		{ id: 'repeatedSequence', label: 'Repeated sequences', swatchColor: 'bg-purple-500', group: 'bucket', test: (r) => r.source === 'repeated_sequence' || r.source === 'token', defaultHide: false },
		// --- Source axis (evidence_tier): why to trust the word - User >
		// Dictionary > Corpus > None. Garbage lives in the Other row below -
		// it's its own is_garbage boolean, not an evidence_tier value, and the
		// row/card's own red tint plus the "not allowed" quick-action icon
		// already flag it without a chip duplicating that here.
		{ id: 'userTier', label: 'User', swatchColor: 'bg-indigo-500', group: 'tier', test: (r) => r.is_user_word, defaultHide: false },
		{ id: 'dictionaryTier', label: 'Dictionary', swatchColor: 'bg-blue-500', group: 'tier', test: (r) => r.evidence_tier === 'dictionary', defaultHide: false },
		{ id: 'corpusTier', label: 'Corpus', swatchColor: 'bg-teal-500', group: 'tier', test: (r) => r.evidence_tier === 'corpus', defaultHide: false },
		{ id: 'noneTier', label: 'None', swatchColor: 'bg-gray-400', group: 'tier', test: (r) => r.evidence_tier === 'unknown', defaultHide: false },
		// --- Other: orthogonal display states, not part of either axis.
		// Starred has no resolved WordResult field (unlike garbage/hidden/
		// user-word) - it's the same separately-fetched `starredWords` Set
		// the row/card quick-actions already use, so this stays live via
		// closure rather than needing a backend round trip of its own.
		{ id: 'starred', label: 'Starred', swatchColor: 'bg-yellow-500', group: 'other', test: (r) => starredWords.has(r.word), defaultHide: false },
		{ id: 'hidden', label: 'Hidden', swatchColor: 'bg-gray-400', group: 'other', test: (r) => r.is_hidden, defaultHide: true },
		{ id: 'garbage', label: 'Garbage', swatchColor: 'bg-red-500', group: 'other', test: (r) => r.is_garbage, defaultHide: true },
		{ id: 'nonChinese', label: 'Non-Chinese', swatchColor: 'bg-gray-400', group: 'other', test: (r) => !containsChinese(r.word), defaultHide: true },
	];

	let bucketState: Record<string, BucketFilterState> = $state(
		Object.fromEntries(BUCKETS.map((b) => [b.id, resolveStoredBucketState(storedFilters.buckets?.[b.id], b.defaultHide)]))
	);

	// Whether the Filters panel (the three bucket-group rows) is expanded.
	// Persisted like every other filter preference below; a first-ever
	// visit (no stored preference at all) collapses it on narrow viewports
	// in onMount, so the page opens uncluttered there - same sm breakpoint
	// this file already switches on elsewhere (the mobile card list vs.
	// desktop table).
	let filtersOpen = $state(storedFilters.filtersOpen ?? true);

	const BUCKET_STATE_CYCLE: BucketFilterState[] = ['show', 'iso', 'hide'];

	// Single click cycles a chip through all three states - no popover, no
	// separate hide/isolate controls to reconcile.
	function cycleBucket(id: string) {
		const current = bucketState[id] ?? 'show';
		const next = BUCKET_STATE_CYCLE[(BUCKET_STATE_CYCLE.indexOf(current) + 1) % BUCKET_STATE_CYCLE.length];
		bucketState = { ...bucketState, [id]: next };
	}

	// The one shared visibility predicate every bucket goes through - no
	// per-bucket special-casing. Hide always wins; multiple simultaneously
	// iso-active buckets compose as OR/union (that's the actual point of
	// isolate: "show me anything in ANY of these buckets at once", not an
	// intersection), never AND.
	function isVisible(r: WordResult): boolean {
		const hideActive = BUCKETS.filter((b) => bucketState[b.id] === 'hide');
		const isoActive = BUCKETS.filter((b) => bucketState[b.id] === 'iso');
		if (hideActive.some((b) => b.test(r))) return false;
		if (isoActive.length > 0 && !isoActive.some((b) => b.test(r))) return false;
		return true;
	}

	// Chips currently off their own default state - powers the Filters
	// panel's disclosure badge.
	const activeBucketCount = $derived(
		BUCKETS.filter((b) => bucketState[b.id] !== (b.defaultHide ? 'hide' : 'show')).length
	);

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
				// Sorts by the DISPLAYED label - now evidence_tier's label,
				// not source's, since the chip in this column shows the
				// evidence tier (User/Dictionary/Corpus/Unknown), not the
				// pipeline-pass source anymore. The column/sort-key name
				// ('source') is unchanged - only what it compares moved to
				// match what's actually rendered.
				cmp = evidenceTierLabel(a.evidence_tier).localeCompare(evidenceTierLabel(b.evidence_tier));
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

	const GROUP_LABELS: Record<string, string> = { bucket: 'Bucket', tier: 'Source', other: 'Other' };
	const bucketGroups = $derived(
		(['bucket', 'tier', 'other'] as const).map((group) => ({
			group,
			label: GROUP_LABELS[group],
			buckets: BUCKETS.filter((b) => b.group === group),
		}))
	);

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
			const toStore: StoredFilters = { buckets: bucketState, minFamiliarityFilter, searchScope, sortColumn, sortDirection, filtersOpen };
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
		if (storedFilters.filtersOpen === undefined && browser && window.innerWidth < 640) {
			filtersOpen = false;
		}
		try {
			// getAnalysis first (not parallel with the rest) - the scoped
			// list endpoints below need analysis.input_text_id to resolve
			// text-scoped entries, which isn't known until this resolves.
			analysis = await api.getAnalysis(id) as Analysis;

			const [knownWordsData, garbageData, starredData] = await Promise.all([
				api.listKnownWords() as Promise<any[]>,
				api.listGarbageWords() as Promise<any[]>,
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

	// WordDetailPanel fires these after its own API calls succeed (see its
	// onFamiliarityChanged/onGarbageMarked docstrings) - without wiring them
	// here, marking familiarity or garbage from the panel updated the
	// panel's own display but left this page's knownWords/garbageWords
	// state (and so the row/card) stale until a manual reload. Same pattern
	// already used for onUserWordEntriesChanged/onVisibilityEntriesChanged
	// just below.
	function handleFamiliarityChanged(word: string, familiarity: number | null) {
		knownWords = { ...knownWords, [word]: familiarity };
	}

	function handleGarbageMarked(word: string) {
		garbageWords = new Set([...garbageWords, word]);
	}

	// Desktop-only (see Phase 1 plan notes): clicking a row opens its info
	// panel, unless the click originated on an actual interactive element
	// within the row (button/link/input/select), which should handle itself.
	// MouseEvent from a row/card click, or KeyboardEvent from the mobile
	// card's onkeydown (Enter/Space) - only `.target` is used, which both
	// share, so one handler covers both activation paths.
	function handleRowClick(event: MouseEvent | KeyboardEvent, word: string) {
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
	// full analysis refetch - see patchResolvedUserWord below for the same
	// approach applied to UserWord.
	function patchResolvedVisibility(word: string, entries: WordVisibilityEntry[]) {
		if (!analysis) return;
		const resolved = resolveVisibilityFromEntries(entries);
		analysis = { ...analysis, results: analysis.results.map((r) => r.word === word ? { ...r, ...resolved } : r) };
	}

	// Mirrors the backend's _resolve_user_word_detail (router.py)
	// client-side, no HTTP - unlike resolveVisibilityFromEntries (a single
	// governing scope), UserWord entries coexist rather than cascading, so
	// this returns every scope present (canonical order) rather than one
	// winner, alongside the resolved affects_dag (analysis > text > global,
	// skipping a NULL opinion, falling back to true).
	function resolveUserWordFromEntries(entries: UserWordDetail[]): { scopes: string[]; resolvedAffectsDag: boolean; scopeAffectsDag: Record<string, boolean | null> } {
		const byScope: Partial<Record<Scope, UserWordDetail>> = {};
		for (const e of entries) {
			const name: Scope = e.scope_analysis_id != null ? 'analysis' : e.scope_input_text_id != null ? 'text' : 'global';
			byScope[name] = e;
		}
		const scopes = (['global', 'text', 'analysis'] as Scope[]).filter((s) => s in byScope);
		const scopeAffectsDag: Record<string, boolean | null> = {};
		for (const s of scopes) scopeAffectsDag[s] = byScope[s]!.affects_dag;
		let resolvedAffectsDag = true;
		for (const name of ['analysis', 'text', 'global'] as Scope[]) {
			const e = byScope[name];
			if (e && e.affects_dag !== null) {
				resolvedAffectsDag = e.affects_dag;
				break;
			}
		}
		return { scopes, resolvedAffectsDag, scopeAffectsDag };
	}

	// Patches the resolved userword_scopes/userword_resolved_affects_dag/
	// userword_scope_affects_dag/is_user_word directly onto analysis.results
	// after a local UserWord mutation (from either the row/card quick-
	// action's own menu or the panel's "Your entries" section), so the
	// quick-action's icon/badge fan update immediately without a full
	// analysis refetch - same "patch locally" approach patchResolvedVisibility
	// already uses.
	function patchResolvedUserWord(word: string, entries: UserWordDetail[]) {
		if (!analysis) return;
		const { scopes, resolvedAffectsDag, scopeAffectsDag } = resolveUserWordFromEntries(entries);
		analysis = {
			...analysis,
			results: analysis.results.map((r) => r.word === word
				? {
					...r,
					is_user_word: scopes.length > 0,
					userword_scopes: scopes,
					userword_resolved_affects_dag: resolvedAffectsDag,
					userword_scope_affects_dag: scopeAffectsDag,
				}
				: r
			),
		};
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
			visibilityMenuOpenFor = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update visibility';
		} finally {
			togglingVisibilityAction = null;
		}
	}

	// Canonical broadest-first order for the UserWord quick-action menu and
	// the badge fan (see userWordScopeBadges) - reads more naturally
	// broadest-first for this menu specifically.
	const SCOPE_ORDER: { value: Scope; label: string }[] = [
		{ value: 'global', label: 'Global' },
		{ value: 'text', label: 'This text' },
		{ value: 'analysis', label: 'This analysis' },
	];

	function affectsDagSummary(affectsDag: boolean | null): string {
		if (affectsDag === false) return 'excluded from segmentation';
		if (affectsDag === null) return 'no segmentation preference set';
		return 'boosts segmentation';
	}

	interface UserWordMenuItem {
		kind: 'entry' | 'add' | 'edit';
		scope?: Scope;
		label: string;
		sublabel?: string;
		entry?: UserWordDetail;
	}

	// One item per scope (an existing entry's summary+remove, or an "+ Add
	// entry" action), plus a final "Edit details..." link to the panel -
	// this popover is a quick-action, not a duplicate of the panel's fuller
	// pronunciation/meaning/notes editor.
	function buildUserWordMenu(rows: UserWordDetail[]): UserWordMenuItem[] {
		const items: UserWordMenuItem[] = [];
		for (const { value: scope, label } of SCOPE_ORDER) {
			const cols = resolveScopeColumns(scope, id, analysis?.input_text_id);
			const entry = rows.find((r) => columnsMatch(r, cols));
			if (entry) {
				items.push({ kind: 'entry', scope, label, sublabel: affectsDagSummary(entry.affects_dag), entry });
			} else {
				items.push({ kind: 'add', scope, label: `+ Add entry (${label})` });
			}
		}
		items.push({ kind: 'edit', label: 'Edit details...' });
		return items;
	}

	// Lazily fetches + caches the up-to-3 raw UserWord rows for a word (via
	// getWordDetail, same endpoint the panel and the visibility quick-action
	// both use) the first time its menu opens - only one menu open at a time.
	async function toggleUserWordMenu(word: string) {
		if (userWordMenuOpenFor === word) {
			userWordMenuOpenFor = null;
			return;
		}
		userWordMenuOpenFor = word;
		if (userWordRowsByWord[word]) return;
		loadingUserWordFor = new Set([...loadingUserWordFor, word]);
		try {
			const detail = await api.getWordDetail(word, id, analysis?.input_text_id) as WordDetail;
			userWordRowsByWord = { ...userWordRowsByWord, [word]: detail.user_words };
		} catch (e: unknown) {
			userWordRowsByWord = { ...userWordRowsByWord, [word]: [] };
		} finally {
			const next = new Set(loadingUserWordFor);
			next.delete(word);
			loadingUserWordFor = next;
		}
	}

	// Creates a bare entry at `scope` - no pronunciation/meaning/notes
	// prompt here (that's what "Edit details..." is for), affects_dag left
	// at its default null ("no opinion, inherit from a broader scope" - see
	// UserWordCreate's docstring, schemas.py). Deliberately does NOT close
	// the menu afterward (unlike applyVisibilityAction) - unlike Visibility's
	// single resolved value, several UserWord entries can coexist, so a user
	// plausibly wants to add/remove more than one in a row without
	// reopening the menu each time.
	async function addUserWordAtScope(word: string, scope: Scope) {
		togglingUserWordAction = word;
		try {
			const created = await api.createUserWord(word, undefined, scopeContext(scope)) as UserWordDetail;
			const cols = resolveScopeColumns(scope, id, analysis?.input_text_id);
			const nextRows = sortMostSpecificFirst([...(userWordRowsByWord[word] ?? []).filter((r) => !columnsMatch(r, cols)), created]);
			userWordRowsByWord = { ...userWordRowsByWord, [word]: nextRows };
			patchResolvedUserWord(word, nextRows);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to add word to your dictionary';
		} finally {
			togglingUserWordAction = null;
		}
	}

	async function removeUserWordEntry(word: string, entry: UserWordDetail) {
		togglingUserWordAction = word;
		try {
			await api.deleteUserWord(word, entry.scope_analysis_id, entry.scope_input_text_id);
			const nextRows = (userWordRowsByWord[word] ?? []).filter((r) => r.id !== entry.id);
			userWordRowsByWord = { ...userWordRowsByWord, [word]: nextRows };
			patchResolvedUserWord(word, nextRows);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to remove word from your dictionary';
		} finally {
			togglingUserWordAction = null;
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

	// WordDetailPanel.svelte now owns its own fetching - this just tells it
	// which word to show and scrolls the triggering row into view (desktop
	// only in practice - the matching mobile card is hidden (display:none)
	// at that viewport, so scrollIntoView on it is a harmless no-op there).
	function openWordDetail(word: string) {
		selectedWordForPanel = word;
		requestAnimationFrame(() => {
			document.querySelector(`[data-word="${CSS.escape(word)}"]`)
				?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
		});
	}

	// WordDetailPanel.svelte's onUserWordEntriesChanged/onVisibilityEntriesChanged
	// callbacks - fired with the word's FULL (unbounded, every-scope) entries
	// list after any change made from the panel. Re-derives this page's own
	// "what's relevant to THIS analysis" view via the exact same isEntryEditable
	// hierarchy rule the panel itself uses to decide editability (an entry is
	// "relevant here" iff it would be editable here - global always, text/
	// analysis only when they match this page's own context), adapts to the
	// shapes patchResolvedUserWord/patchResolvedVisibility already expect, and
	// reuses those to keep the row/card quick-action icons in sync - the same
	// live-update behavior this page already had before the panel was
	// extracted, just re-derived from richer data now.
	function handleUserWordEntriesChanged(word: string, entries: { id: number; scope: 'global' | 'text' | 'analysis'; text_id: number | null; analysis_id: number | null; pronunciation: string | null; meaning: string | null; notes: string | null; affects_dag: boolean | null }[]) {
		const relevant = entries
			.filter((e) => isEntryEditable(e, panelContext))
			.map((e): UserWordDetail => ({
				id: e.id,
				pronunciation: e.pronunciation, meaning: e.meaning, notes: e.notes, affects_dag: e.affects_dag,
				scope_analysis_id: e.scope === 'analysis' ? e.analysis_id : null,
				scope_input_text_id: e.scope === 'text' ? e.text_id : null,
			}));
		userWordRowsByWord = { ...userWordRowsByWord, [word]: relevant };
		patchResolvedUserWord(word, relevant);
	}

	function handleVisibilityEntriesChanged(word: string, entries: { id: number; scope: 'global' | 'text' | 'analysis'; text_id: number | null; analysis_id: number | null; hidden: boolean }[]) {
		const relevant = entries
			.filter((e) => isEntryEditable(e, panelContext))
			.map((e): WordVisibilityEntry => ({
				id: e.id, word,
				hidden: e.hidden,
				scope_analysis_id: e.scope === 'analysis' ? e.analysis_id : null,
				scope_input_text_id: e.scope === 'text' ? e.text_id : null,
			}));
		visibilityRowsByWord = { ...visibilityRowsByWord, [word]: relevant };
		patchResolvedVisibility(word, relevant);
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

	function currentFamiliarity(result: WordResult): number | null {
		if (result.word in knownWords) return knownWords[result.word];
		return result.familiarity;
	}

	// Desktop table's Familiarity column renders this as 5 dots rather than
	// familiarityColor's badge - same hue per score so it still reads as the
	// same scale, just a different shape (a row of dots is denser than a
	// pill badge in a table column). Unfilled dots are a flat bg-gray-200
	// regardless of score - only the filled prefix carries color.
	function familiarityDotColor(score: number): string {
		const colors: Record<number, string> = {
			1: 'bg-red-600',
			2: 'bg-orange-600',
			3: 'bg-yellow-600',
			4: 'bg-green-400',
			5: 'bg-emerald-600',
		};
		return colors[score] ?? 'bg-gray-200';
	}

	function toggleInfo(word: string) {
		const next = new Set(expandedInfo);
		if (next.has(word)) {
			next.delete(word);
		} else {
			next.add(word);
			// Context is folded into this same accordion section on mobile
			// (see the min-[700px]:hidden card list) rather than a separate toggle.
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
		class="w-full flex items-center justify-center gap-1 hover:text-blue-600 {sortColumn === column ? 'text-blue-600' : ''}"
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
		<circle cx="10" cy="10" r="7.25" />
		<path d="M5.15 14.85l9.7-9.7" />
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
     existing icon-badge system for scope elsewhere in this app - this is a
     new, minimal visual purpose-built for the visibility quick-action, not
     a reuse of anything pre-existing. -->
{#snippet scopeBadge(scope: string)}
	{#if scope !== 'default'}
		<span
			class="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-white border border-current text-[8px] leading-[10px] font-bold flex items-center justify-center pointer-events-none"
			title={scope === 'global' ? 'Global' : scope === 'text' ? 'This text' : 'This analysis'}
		>{scope === 'global' ? 'G' : scope === 'text' ? 'T' : 'A'}</span>
	{/if}
{/snippet}

<!-- Multi-badge fan for the UserWord quick-action - same size/position
     units as scopeBadge's single badge, generalized to 0-3 simultaneous
     badges since UserWord entries coexist rather than cascading (unlike
     WordVisibility's single governing scope). Canonical left-to-right
     order Global/Text/Analysis, filtered to only present scopes; the last
     (rightmost) present badge sits at the same corner position scopeBadge's
     single badge always used, each earlier badge shifts left by a fixed
     step and sits at a lower z-index, so later-in-order badges appear to
     sit on top of/in front of earlier ones - a fanned-stack look. With one
     scope present this is pixel-identical (position-wise) to the old
     single-badge look.

     Each badge is colored by ITS OWN scope's affects_dag (scopeAffectsDag,
     from userword_scope_affects_dag) - light-bg/dark-text emerald when
     that entry boosts segmentation, light-bg/dark-text slate otherwise
     (false or null/no-preference, collapsed together the same way the
     panel's own per-entry bookmark icon already treats them) - the same
     filled-chip language the familiarity/HSK/source badges elsewhere on
     this page already use (e.g. the "Mastered" familiarity chip), not the
     white-background-plus-colored-border-and-text scopeBadge itself still
     uses - colored text on a plain white circle has no other precedent
     anywhere else in this app. This is deliberately NOT the icon's own
     color (see userWordAction below, which is neutral/existence-only) -
     the whole point is showing every present scope's actual setting
     instead of only the one resolved winner's. -->

{#snippet userWordScopeBadges(scopes: string[], scopeAffectsDag: Record<string, boolean | null>)}
	{@const present = (['global', 'text', 'analysis'] as const).filter((s) => scopes.includes(s))}
	{#each present as scope, i}
		{@const distanceFromCorner = present.length - 1 - i}
		<span
			class="absolute w-3 h-3 rounded-full text-[8px] leading-[10px] font-bold flex items-center justify-center pointer-events-none {scopeAffectsDag[scope] ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}"
			style="bottom: -0.125rem; right: {-0.125 + distanceFromCorner * 0.5}rem; z-index: {i + 1};"
			title="{scope === 'global' ? 'Global' : scope === 'text' ? 'This text' : 'This analysis'}: {scopeAffectsDag[scope] === false ? 'excluded from segmentation' : scopeAffectsDag[scope] === null ? 'no segmentation preference set' : 'boosts segmentation'}"
		>{scope === 'global' ? 'G' : scope === 'text' ? 'T' : 'A'}</span>
	{/each}
{/snippet}

<!-- One chip per filter bucket - swatch + label + count (always against
     the FULL unfiltered result set, see bucketCount) - a single click
     cycles it through all three states: show -> isolate -> hide -> show.
     Isolate uses the app's general "selected/active" blue (matching
     selected familiarity-score buttons, the selected-row highlight)
     plus an "only" mark; hide uses a strikethrough label + a small red
     dot, both visible without opening anything - no popover, unlike the
     old two-checkbox version. -->
{#snippet filterChip(bucket: Bucket)}
	{@const state = bucketState[bucket.id] ?? 'show'}
	{@const count = bucketCount(bucket)}
	<button
		type="button"
		onclick={() => cycleBucket(bucket.id)}
		aria-pressed={state === 'iso'}
		class="flex items-center gap-1.5 pl-2 pr-2.5 py-1.5 rounded-full text-sm border transition-colors
		{state === 'iso' ? 'bg-blue-100 border-blue-300 text-blue-700' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-100'}
		{state === 'hide' ? 'opacity-60' : ''}"
		title="{bucket.label}: {state === 'iso' ? 'isolated - showing only this' : state === 'hide' ? 'hidden' : 'shown'} — click to cycle Show → Isolate → Hide"
	>
		<span class="w-1.5 h-1.5 rounded-full {bucket.swatchColor}" aria-hidden="true"></span>
		<span class={state === 'hide' ? 'line-through' : ''}>{bucket.label}</span>
		<span class="text-xs {state === 'iso' ? 'text-blue-500' : 'text-gray-400'}">({count})</span>
		{#if state === 'iso'}
			<span class="text-[9px] font-bold uppercase tracking-wide text-blue-500">only</span>
		{:else if state === 'hide'}
			<span class="w-1.5 h-1.5 rounded-full bg-red-400" aria-hidden="true"></span>
		{/if}
	</button>
{/snippet}

<!-- Menu-items list shared by visibilityAction's two containers below (the
     sm+ dropdown and the below-sm bottom sheet) - written once, rendered
     from both, rather than duplicated. -->
{#snippet visibilityMenuItems(result: WordResult)}
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
{/snippet}

<!-- Visibility quick-action, reused by both the desktop table row and the
     mobile card. Icon reflects resolved is_hidden; the corner badge shows
     hidden_governing_scope (omitted entirely when "default" - see
     scopeBadge above). Click opens a menu built by buildVisibilityMenu,
     lazily fetching+caching that word's raw scope rows on first open (see
     toggleVisibilityMenu).

     Two sibling containers, gated by the same open/close state, split by
     breakpoint via CSS (hidden min-[700px]:block / min-[700px]:hidden) rather than JS - the
     700px+ dropdown positions absolute right-0, fine when the trigger sits
     near a wide row's right edge; below 700px the same trigger sits near the
     LEFT of a narrow card, where that same dropdown would overflow off the
     left edge of the screen, so it becomes a bottom sheet instead (same
     treatment WordDetailPanel's own modal uses, for visual consistency). -->
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
			<!-- sm and up: unchanged dropdown, invisible click-catcher backdrop.
			     stopPropagation - without it this click bubbles up through the
			     enclosing row/card's own onclick (position:fixed only affects
			     paint, not DOM position - this div is still a descendant of the
			     row), which would immediately reopen the word-detail panel
			     right after the popover closes. -->
			<div class="hidden min-[700px]:block fixed inset-0 z-40" onclick={(e) => { e.stopPropagation(); visibilityMenuOpenFor = null; }} role="presentation"></div>
			<div
				class="hidden min-[700px]:block absolute right-0 top-full mt-1 z-50 w-56 bg-white rounded-lg shadow-lg border border-gray-100 py-1"
				onclick={(e) => e.stopPropagation()}
				role="presentation"
			>
				{@render visibilityMenuItems(result)}
			</div>

			<!-- below 700px: bottom sheet, its own dimmed backdrop - same
			     stopPropagation reasoning as the dropdown backdrop above. -->
			<div class="min-[700px]:hidden fixed inset-0 z-40 bg-black/30" onclick={(e) => { e.stopPropagation(); visibilityMenuOpenFor = null; }} role="presentation"></div>
			<div
				class="min-[700px]:hidden fixed inset-x-0 bottom-0 z-50 bg-white rounded-t-2xl shadow-sm p-4 max-h-[70vh] overflow-y-auto"
				onclick={(e) => e.stopPropagation()}
				role="presentation"
			>
				<div class="flex items-center justify-between mb-2">
					<p class="text-sm font-medium text-gray-700">{result.word}</p>
					<button onclick={() => visibilityMenuOpenFor = null} class="text-sm text-blue-600 hover:text-blue-800">Close</button>
				</div>
				{@render visibilityMenuItems(result)}
			</div>
		{/if}
	</div>
{/snippet}

<!-- Menu-items list shared by userWordAction's two containers below (the
     sm+ dropdown and the below-sm bottom sheet) - written once, rendered
     from both, rather than duplicated. -->
{#snippet userWordMenuItems(result: WordResult)}
	{#if loadingUserWordFor.has(result.word)}
		<p class="text-xs text-gray-400 px-3 py-2">Loading...</p>
	{:else}
		{#each buildUserWordMenu(userWordRowsByWord[result.word] ?? []) as item}
			{#if item.kind === 'entry'}
				<div class="px-3 py-1.5 flex items-center justify-between gap-2">
					<div class="min-w-0">
						<p class="text-sm text-gray-700 truncate">{item.label}</p>
						<p class="text-xs text-gray-400 truncate">{item.sublabel}</p>
					</div>
					<button
						onclick={() => removeUserWordEntry(result.word, item.entry!)}
						disabled={togglingUserWordAction === result.word}
						class="text-xs text-red-400 hover:text-red-600 disabled:opacity-50 shrink-0"
					>
						Remove
					</button>
				</div>
			{:else if item.kind === 'add'}
				<button
					onclick={() => addUserWordAtScope(result.word, item.scope!)}
					disabled={togglingUserWordAction === result.word}
					class="w-full text-left px-3 py-1.5 text-sm text-blue-600 hover:bg-gray-50 disabled:opacity-50"
				>
					{item.label}
				</button>
			{:else}
				<button
					onclick={() => { userWordMenuOpenFor = null; openWordDetail(result.word); }}
					class="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 border-t border-gray-100 mt-1"
				>
					{item.label}
				</button>
			{/if}
		{/each}
	{/if}
{/snippet}

<!-- UserWord quick-action, reused by both the desktop table row and the
     mobile card - structured exactly like visibilityAction above (relative
     wrapper, backdrop-click-to-close popover, sm+ dropdown vs. below-sm
     bottom sheet - see visibilityAction's own comment for why), but unlike
     Visibility's single resolved value, UserWord entries coexist across up
     to 3 scopes at once (see UserWord's docstring, models.py), so this
     can't be a single toggle: filled state is userword_scopes.length > 0
     (the actual bug this popover originally fixed - previously this only
     ever reflected a GLOBAL-only Set, see CLAUDE.md). The icon itself is
     existence-only (slate when present, gray when not - same neutral
     treatment visibilityAction's own icon uses) rather than colored by the
     resolved affects_dag - showing only the resolved winner's color there
     would hide the other present scopes' own settings, which is exactly
     what the per-scope badge fan (userWordScopeBadges) exists to surface
     instead: one badge per scope present, each colored by ITS OWN
     affects_dag. The menu lists all 3 scopes - an existing entry's summary
     + remove, or a bare "+ Add entry" for a scope with none - plus a final
     "Edit details..." link to the panel's fuller pronunciation/meaning/
     notes editor, which this popover deliberately doesn't duplicate. -->
{#snippet userWordAction(result: WordResult)}
	<div class="relative inline-block">
		<button
			onclick={(e) => { e.stopPropagation(); toggleUserWordMenu(result.word); }}
			class="p-1.5 rounded {result.userword_scopes.length > 0 ? 'text-slate-600' : 'text-gray-400'} hover:text-blue-600 hover:bg-blue-50"
			title={result.userword_scopes.length > 0 ? 'In your dictionary — click for options' : 'Add to your custom dictionary — click for options'}
			aria-label="User word options"
		>
			{@render iconBookmark(result.userword_scopes.length > 0)}
		</button>
		{@render userWordScopeBadges(result.userword_scopes, result.userword_scope_affects_dag)}
		{#if userWordMenuOpenFor === result.word}
			<!-- sm and up: unchanged dropdown, invisible click-catcher backdrop.
			     stopPropagation - see visibilityAction's matching backdrop
			     comment for why (this div is still a DOM descendant of the
			     row/card despite position:fixed, so an unguarded click bubbles
			     up into the row's own onclick and reopens the detail panel). -->
			<div class="hidden min-[700px]:block fixed inset-0 z-40" onclick={(e) => { e.stopPropagation(); userWordMenuOpenFor = null; }} role="presentation"></div>
			<div
				class="hidden min-[700px]:block absolute right-0 top-full mt-1 z-50 w-60 bg-white rounded-lg shadow-lg border border-gray-100 py-1"
				onclick={(e) => e.stopPropagation()}
				role="presentation"
			>
				{@render userWordMenuItems(result)}
			</div>

			<!-- below 700px: bottom sheet, its own dimmed backdrop - same
			     stopPropagation reasoning as the dropdown backdrop above. -->
			<div class="min-[700px]:hidden fixed inset-0 z-40 bg-black/30" onclick={(e) => { e.stopPropagation(); userWordMenuOpenFor = null; }} role="presentation"></div>
			<div
				class="min-[700px]:hidden fixed inset-x-0 bottom-0 z-50 bg-white rounded-t-2xl shadow-sm p-4 max-h-[70vh] overflow-y-auto"
				onclick={(e) => e.stopPropagation()}
				role="presentation"
			>
				<div class="flex items-center justify-between mb-2">
					<p class="text-sm font-medium text-gray-700">{result.word}</p>
					<button onclick={() => userWordMenuOpenFor = null} class="text-sm text-blue-600 hover:text-blue-800">Close</button>
				</div>
				{@render userWordMenuItems(result)}
			</div>
		{/if}
	</div>
{/snippet}

<div class="min-h-screen bg-gray-50">
	<!-- Below sm (640px - Tailwind's own breakpoint, unrelated to this
	     page's desktop-table/mobile-card swap, which now happens at 700px;
	     see the hidden min-[700px]:block / min-[700px]:hidden pair on the
	     results list): the title cluster and the reading-view/counts cluster stack
	     as two full-width rows instead of sharing one - at sm+, unchanged
	     single-row layout. The title itself gets min-w-0 + truncate (plus a
	     title= attribute for the full value) so it's protected from being
	     squeezed toward zero width even before the stacking kicks in - that
	     protection, not the stacking, is what stops a spaceless Chinese
	     title from wrapping one character per line. -->
	<nav class="bg-white shadow-sm px-6 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 sm:gap-0">
		<div class="flex flex-wrap items-center gap-4 min-w-0">
			<a href="/" class="text-gray-600 hover:text-gray-800 text-sm shrink-0">← Back</a>
			<h1 class="text-xl font-bold text-gray-800 min-w-0 truncate" title={analysis?.title ?? 'Analysis Results'}>
				{analysis?.title ?? 'Analysis Results'}
			</h1>
			{#if analysis}
				<a
					href="/input-texts/{analysis.input_text_id}"
					class="text-sm text-blue-600 hover:text-blue-800 shrink-0"
				>
					View source text
				</a>
			{/if}
		</div>
		{#if analysis}
			<div class="flex flex-wrap items-center gap-4">
				<label class="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer shrink-0">
					<input type="checkbox" bind:checked={readingViewOn} class="rounded" />
					Reading view
				</label>
				<div class="text-sm text-gray-500 flex flex-wrap gap-4">
					<span>{analysis.unique_words} unique words</span>
					<span>{analysis.total_words} total occurrences</span>
				</div>
			</div>
		{/if}
	</nav>

	<main class="max-w-5xl lg:max-w-6xl 2xl:max-w-7xl mx-auto px-6 py-8">
		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		{#if readingViewOn && analysis}
			<ReadingView analysisId={id} textTitle={analysis.title} analysisTitle={analysis.title} />
		{:else}
		<!-- Toolbar: search, familiarity threshold, sort, and the result count
		     in one row that wraps naturally on narrow screens instead of nine
		     separately-floating controls. The three bucket-group rows below
		     (Bucket/Source/Other, see BUCKETS above) collapse behind the
		     Filters disclosure so this toolbar is the only thing always
		     visible. -->
		<div class="bg-white rounded-lg shadow-sm p-4 mb-4">
			<div class="flex flex-wrap items-center gap-3">
				<div class="flex items-center gap-2 flex-1 min-w-[160px] max-w-xs">
					<input
						type="search"
						bind:value={searchQuery}
						placeholder="Search words..."
						class="border border-gray-300 rounded px-2 py-1 text-sm w-full"
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

				<span class="text-sm text-gray-400 sm:ml-auto">
					Showing {filteredResults().length} of {analysis?.results.length ?? 0} words
				</span>
			</div>

			<!-- Filters disclosure - collapsed by default on a first-ever
			     narrow-viewport visit (see onMount), remembers whatever the
			     user leaves it at otherwise. The badge counts chips off their
			     default state and always occupies the same box (styled muted
			     at zero rather than unmounting), so toggling it never shifts
			     the toolbar's height. -->
			<button
				type="button"
				onclick={() => filtersOpen = !filtersOpen}
				aria-expanded={filtersOpen}
				aria-controls="filter-groups"
				class="mt-3 pt-3 border-t border-gray-100 w-full flex items-center gap-2 text-left"
			>
				<svg class="w-3.5 h-3.5 text-gray-400 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3 4h14l-5.5 6.5v5L8.5 17v-6.5L3 4z"/></svg>
				<span class="text-sm font-semibold text-gray-700">Filters</span>
				<span class="text-xs font-bold rounded-full px-2 py-0.5 border {activeBucketCount > 0 ? 'text-blue-700 bg-blue-50 border-blue-200' : 'text-gray-400 bg-transparent border-gray-200'}">
					{activeBucketCount > 0 ? `${activeBucketCount} active` : 'None active'}
				</span>
				<svg class="w-3.5 h-3.5 text-gray-400 ml-auto transition-transform {filtersOpen ? '' : '-rotate-90'}" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8l4 4 4-4"/></svg>
			</button>

			{#if filtersOpen}
				<div id="filter-groups" class="flex flex-col gap-1.5 mt-3">
					{#each bucketGroups as { group, label, buckets } (group)}
						<div class="flex flex-wrap items-center gap-1.5 bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-2">
							<span class="text-[10px] font-bold text-gray-400 uppercase tracking-wide pr-1">{label}</span>
							{#each buckets as bucket}
								{@render filterChip(bucket)}
							{/each}
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<div class="flex flex-col min-[700px]:flex-row gap-4">
			<!-- Results table (sm and up - see the mobile card list below for < sm) -->
			<div class="hidden min-[700px]:block flex-1 min-w-0 bg-white rounded-lg shadow-sm overflow-hidden">
				{#if loading}
					<p class="text-gray-500 p-4">Loading...</p>
				{:else if analysis}
					<div class="overflow-x-auto">
					<table class="w-full">
						<thead class="bg-gray-50 border-b border-gray-200">
							<tr>
								<th class="text-center px-4 py-3 text-sm font-medium text-gray-700">{@render sortHeader('Word', 'word')}</th>
								<th class="text-center px-4 py-3 text-sm font-medium text-gray-700">{@render sortHeader('Count', 'count')}</th>
								<th class="text-center px-4 py-3 text-sm font-medium text-gray-700">Bucket</th>
								<th class="text-center px-4 py-3 text-sm font-medium text-gray-700">{@render sortHeader('Source', 'source')}</th>
								<th class="text-center px-4 py-3 text-sm font-medium text-gray-700">{@render sortHeader('Familiarity', 'familiarity')}</th>
								<th class="text-center px-4 py-3 text-sm font-medium text-gray-700">Actions</th>
								<th class="px-2 py-3"><span class="sr-only">Open details</span></th>
							</tr>
						</thead>
						<tbody class="divide-y divide-gray-100">
							{#each filteredResults() as result}
								<tr
									data-word={result.word}
									onclick={(e) => handleRowClick(e, result.word)}
									class="group cursor-pointer hover:bg-gray-50 {result.source === 'longest_match_only' ? 'bg-amber-50/40' : ''} {garbageWords.has(result.word) ? 'bg-red-50/40' : ''} {selectedWordForPanel === result.word ? '!bg-blue-50 ring-1 ring-inset ring-blue-200' : ''}"
								>
									<td class="px-4 py-3 text-lg font-medium">
										<div class="flex items-center justify-center gap-1.5">
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
									<td class="px-4 py-3 text-gray-600 text-center">{result.count}</td>
									<td class="px-4 py-3 text-center">
										<span
											class="inline-block text-center text-xs px-2 py-1 rounded-full {bucketColor(result.source)}"
											title={result.source === 'longest_match_only' ? 'Found only by the legacy longest-matching pass — not confirmed by the main segmenter. Likely a dictionary gap; review before trusting it.' : ''}
										>
											{bucketLabel(result.source)}
										</span>
									</td>
									<td class="px-4 py-3 text-center">
										<span class="inline-block text-center text-xs px-2 py-1 rounded-full {evidenceTierColor(result.evidence_tier)}">
											{evidenceTierLabel(result.evidence_tier)}
										</span>
									</td>
									<td class="px-4 py-3 text-center">
										<div class="flex items-center justify-center gap-0.5">
											{#each [1, 2, 3, 4, 5] as score}
												<button
													onclick={() => setFamiliarity(result.word, score)}
													disabled={updatingWord === result.word}
													class="p-1 rounded hover:bg-gray-100 disabled:opacity-50"
													title={familiarityLabel(score)}
													aria-label={familiarityLabel(score)}
													aria-pressed={currentFamiliarity(result) === score}
												>
													<span class="block w-2 h-2 rounded-full {currentFamiliarity(result) !== null && score <= currentFamiliarity(result)! ? familiarityDotColor(currentFamiliarity(result)!) : 'bg-gray-200'}"></span>
												</button>
											{/each}
											<button
												onclick={() => setFamiliarity(result.word, null)}
												disabled={updatingWord === result.word || currentFamiliarity(result) === null}
												class="p-1 rounded hover:bg-gray-100 disabled:opacity-50 text-gray-400 hover:text-gray-600 ml-0.5 {currentFamiliarity(result) === null ? 'invisible' : ''}"
												title="Clear familiarity"
												aria-label="Clear familiarity"
											>
												<span class="inline-flex items-center justify-center w-2 h-2 text-[10px] leading-none">✕</span>
											</button>
										</div>
									</td>
									<td class="px-4 py-3 min-w-[92px]">
										<div class="flex flex-wrap justify-center gap-0.5 items-center">
											{@render visibilityAction(result)}
											{@render userWordAction(result)}
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
									<td class="px-2 py-3">
										<div class="flex justify-end">
											<button
												onclick={() => openWordDetail(result.word)}
												class="p-1 rounded text-gray-300 hover:text-blue-600 group-hover:text-gray-400"
												aria-label="View details for {result.word}"
											>
												<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
													<path d="M7.5 5l5.5 5-5.5 5" />
												</svg>
											</button>
										</div>
									</td>
								</tr>
								{#if expandedContext.has(result.word)}
									<tr class="bg-gray-50">
										<td colspan="7" class="px-4 py-3 border-t border-gray-100">
											{@render contextList(result.word)}
										</td>
									</tr>
								{/if}
							{/each}
						</tbody>
					</table>
					</div>
				{/if}
			</div>

			<!-- Mobile card list (< sm) - collapsed to word + two accordion
			     toggles: "+" for read-only info, hamburger for the interactive
			     controls. Independent per-word toggles (expandedInfo/expandedActions),
			     everything below reuses the exact same handlers/derived helpers
			     and icon snippets the desktop table above uses. -->
			<div class="min-[700px]:hidden bg-white rounded-lg shadow-sm overflow-hidden divide-y divide-gray-100">
				{#if loading}
					<p class="text-gray-500 p-4">Loading...</p>
				{:else if analysis}
					{#each filteredResults() as result}
						<div
							class="{result.source === 'longest_match_only' ? 'bg-amber-50/40' : ''} {garbageWords.has(result.word) ? 'bg-red-50/40' : ''}"
						>
							<div
								role="button"
								tabindex="0"
								onclick={(e) => handleRowClick(e, result.word)}
								onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleRowClick(e, result.word); } }}
								class="flex items-center justify-between gap-2 px-4 py-3 cursor-pointer"
							>
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
										class="inline-block text-center text-xs px-2 py-1 rounded-full {bucketColor(result.source)}"
										title={result.source === 'longest_match_only' ? 'Found only by the legacy longest-matching pass — not confirmed by the main segmenter. Likely a dictionary gap; review before trusting it.' : ''}
									>
										{bucketLabel(result.source)}
									</span>
									<span class="inline-block text-center text-xs px-2 py-1 rounded-full {evidenceTierColor(result.evidence_tier)}">
										{evidenceTierLabel(result.evidence_tier)}
									</span>
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
										{@render visibilityAction(result)}
										{@render userWordAction(result)}
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

			<!-- Word detail panel - below `lg`, WordDetailModal presents this as
			     a fixed bottom-sheet overlay rather than a block in normal
			     document flow. Two separate reasons this page needs that
			     overlay all the way up to `lg`, not just on mobile: below
			     `sm` the card list above it can be very long, so a
			     normal-flow panel would render off-screen at the bottom,
			     invisible until scrolled all the way down; between `sm` and
			     `lg`, the desktop *table* is already showing (it only needs
			     ~640px to look fine on its own), but a table narrow enough to
			     fit there has no room left to also fit a 288px side panel
			     next to it without squeezing "Familiarity"/"Actions" into
			     unreadable overlap - so the panel keeps overlaying instead of
			     joining the flex row until there's actually room (`lg`,
			     1024px) for both side by side. See WordDetailModal.svelte for
			     the shared mechanism (lg:contents, the width-fix wrapper). -->
			<WordDetailModal
				word={selectedWordForPanel}
				context={panelContext}
				onClose={() => selectedWordForPanel = null}
				onUserWordEntriesChanged={(entries) => handleUserWordEntriesChanged(selectedWordForPanel!, entries)}
				onVisibilityEntriesChanged={(entries) => handleVisibilityEntriesChanged(selectedWordForPanel!, entries)}
				onFamiliarityChanged={(familiarity) => handleFamiliarityChanged(selectedWordForPanel!, familiarity)}
				onGarbageMarked={() => handleGarbageMarked(selectedWordForPanel!)}
			/>
		</div>
		{/if}
	</main>
</div>
