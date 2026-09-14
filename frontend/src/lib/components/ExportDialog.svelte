<script lang="ts">
	import * as api from '$lib/api';
	import { loadExportPreferences, type ExportPreferences } from '$lib/exportPreferences';
	import { buildPlecoExport, sanitizeFilename, type ExportWordData, type ExportableWord } from '$lib/pleco';

	// Opened from analyze/[id]/+page.svelte's toolbar. Everything the user
	// might want to change per-export lives on the Account page
	// (ExportPreferences, backend-persisted - see exportPreferences.ts) -
	// this dialog is deliberately thin: load those settings plus the bulk
	// per-word data, show a read-only summary of the settings with a link
	// to go edit them, and offer the one thing that's genuinely an
	// export-time decision (respect the current filter or not) before
	// triggering the download.
	let {
		analysisId,
		textTitle,
		allWords,
		filteredWords,
		onClose,
	}: {
		analysisId: number;
		textTitle: string | null;
		allWords: ExportableWord[];
		filteredWords: ExportableWord[];
		onClose: () => void;
	} = $props();

	let loading = $state(true);
	let error = $state('');
	let prefs: ExportPreferences | null = $state(null);
	let exportData: ExportWordData[] | null = $state(null);
	// Defaults to respecting the current filter - "what I'm looking at is
	// what I get" is the least-surprising default; unchecking it exports
	// every word in the analysis regardless of the filter bar's state.
	let respectFilter = $state(true);
	// Set once a download has actually fired (see handleExport) - a mobile
	// browser's own download UI is easy to miss entirely (no visible
	// progress, no obvious "saved" toast the way a desktop browser's
	// download tray gives you), so this dialog now surfaces its own
	// explicit confirmation instead of just closing the instant the
	// browser is asked to save the file. Holds the filename so the
	// confirmation can name the exact file that landed in Downloads.
	let downloadedFilename: string | null = $state(null);

	$effect(() => {
		loading = true;
		error = '';
		Promise.all([loadExportPreferences(), api.getExportData(analysisId)])
			.then(([loadedPrefs, data]) => {
				prefs = loadedPrefs;
				exportData = (data as { words: ExportWordData[] }).words;
			})
			.catch((e: unknown) => {
				error = e instanceof Error ? e.message : 'Failed to load export data';
			})
			.finally(() => {
				loading = false;
			});
	});

	const wordsToExport = $derived(respectFilter ? filteredWords : allWords);

	// Short, read-only recap of the account-level settings - not editable
	// here, just enough context to know what's about to be exported before
	// clicking through to /profile to change anything.
	const sourcesSummary = $derived.by(() => {
		if (!prefs || !prefs.includeDefinitions) return null;
		const s = prefs.definitionSources;
		const parts: string[] = [];
		if (s.corpusFrequency) parts.push('Corpus frequency');
		if (s.hsk) parts.push('HSK');
		if (s.cedict) parts.push('CC-CEDICT');
		const userScopes = [s.userGlobal && 'Global', s.userText && 'This text', s.userAnalysis && 'This analysis'].filter(Boolean);
		if (userScopes.length > 0) parts.push(`Your definitions (${userScopes.join(', ')})`);
		return parts.length > 0 ? parts.join(', ') : 'None selected';
	});

	function downloadText(filename: string, content: string) {
		const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = filename;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);
	}

	function handleExport() {
		if (!prefs || !exportData) return;
		const categoryTitle = textTitle ?? 'Untitled text';
		const content = buildPlecoExport(categoryTitle, wordsToExport, exportData, prefs);
		const filename = `${sanitizeFilename(textTitle)}.txt`;
		try {
			downloadText(filename, content);
			// Stay open and show a confirmation rather than closing
			// immediately - see downloadedFilename's own docstring above for
			// why (a mobile browser gives no feedback of its own).
			downloadedFilename = filename;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to start the download';
		}
	}
</script>

<div class="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4" onclick={onClose} role="presentation">
	<div
		class="bg-white dark:bg-slate-900 rounded-lg shadow-lg w-full max-w-md p-6"
		onclick={(e) => e.stopPropagation()}
		role="presentation"
	>
		<h2 class="text-sm font-semibold text-gray-700 dark:text-slate-300 mb-4">Export to Pleco</h2>

		{#if downloadedFilename}
			<!-- Explicit success confirmation, held open until the user
			     dismisses it - see downloadedFilename's own docstring for why
			     this dialog doesn't just close the instant the download
			     fires. -->
			<div class="flex items-start gap-2 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-400 px-3 py-2.5 rounded text-sm mb-4">
				<svg class="w-4 h-4 mt-0.5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M4 10.5l3.5 3.5L16 6" />
				</svg>
				<span>Downloaded <span class="font-medium">{downloadedFilename}</span>.</span>
			</div>
			<div class="flex justify-end">
				<button
					onclick={onClose}
					class="text-sm px-4 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600"
				>
					Done
				</button>
			</div>
		{:else if loading}
			<p class="text-sm text-gray-500 dark:text-slate-400">Loading…</p>
		{:else if error}
			<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-3 py-2 rounded text-sm mb-3">
				{error}
			</div>
		{:else if prefs}
			<dl class="text-xs text-gray-500 dark:text-slate-400 space-y-1 mb-4">
				<div class="flex justify-between gap-4">
					<dt>Pinyin</dt>
					<dd class="text-gray-700 dark:text-slate-300">{prefs.includePinyin ? 'Included' : 'Not included'}</dd>
				</div>
				<div class="flex justify-between gap-4">
					<dt>Definitions</dt>
					<dd class="text-gray-700 dark:text-slate-300 text-right">{sourcesSummary ?? 'Not included'}</dd>
				</div>
			</dl>
			<a href="/profile" class="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 block mb-4">
				Edit export settings
			</a>

			<label class="flex items-center gap-2 text-sm text-gray-700 dark:text-slate-300 mb-4">
				<input type="checkbox" bind:checked={respectFilter} class="rounded border-gray-300" />
				Respect current filters
			</label>

			<p class="text-xs text-gray-400 dark:text-slate-500 mb-4">
				{wordsToExport.length} word{wordsToExport.length === 1 ? '' : 's'} will be exported, grouped into
				Main/Extra/Sequences categories under "{textTitle ?? 'Untitled text'}".
			</p>

			<div class="flex justify-end gap-2">
				<button
					onclick={onClose}
					class="text-sm px-4 py-1.5 text-gray-600 dark:text-slate-400 hover:text-gray-800 dark:hover:text-slate-200"
				>
					Cancel
				</button>
				<button
					onclick={handleExport}
					disabled={wordsToExport.length === 0}
					class="text-sm px-4 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
				>
					Export
				</button>
			</div>
		{/if}
	</div>
</div>
