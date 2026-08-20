<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	interface WordResult {
		word: string;
		count: number;
		source: string;
		familiarity: number | null;
	}

	interface HskForm {
		traditional: string | null;
		pinyin: string | null;
		meanings: string[];
		classifiers: string[];
	}

	interface WordDetail {
		word: string;
		frequency: number | null;
		hsk_v2_2012: number | null;
		hsk_v3_2021: number | null;
		hsk_v3_2026: number | null;
		forms: HskForm[];
	}

	interface Analysis {
		input_text_id: number;
		title: string | null;
		total_words: number;
		unique_words: number;
		results: WordResult[];
	}

	let analysis: Analysis | null = $state(null);
	let loading = $state(true);
	let error = $state('');
	let updatingWord = $state('');
	let garbageWords = $state(new Set<string>());
	let knownWords = $state<Record<string, number | null>>({});
	let hideNonChinese = $state(true);
	let hideSupplemental = $state(false);
	let selectedWord: WordDetail | null = $state(null);
	let loadingDetail = $state(false);
	let minFamiliarityFilter = $state(4);

	const id = $derived(parseInt($page.params.id));

	function containsChinese(word: string): boolean {
		return /[\u4e00-\u9fff]/.test(word);
	}

	const filteredResults = $derived(() => {
		if (!analysis) return [];
		return analysis.results.filter((r) => {
			if (garbageWords.has(r.word)) return false;
			if (hideNonChinese && !containsChinese(r.word)) return false;
			if (hideSupplemental && r.source === 'longest_match_only') return false;
			const familiarity = knownWords[r.word] ?? r.familiarity;
			if (familiarity !== null && familiarity !== undefined && familiarity >= minFamiliarityFilter) return false;
			return true;
		});
	});

	const supplementalCount = $derived(() => {
		if (!analysis) return 0;
		return analysis.results.filter((r) => r.source === 'longest_match_only').length;
	});

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			const [analysisData, knownWordsData, garbageData] = await Promise.all([
				api.getAnalysis(id) as Promise<Analysis>,
				api.listKnownWords() as Promise<any[]>,
				api.listGarbageWords() as Promise<any[]>,
			]);

			analysis = analysisData;

			const kwMap: Record<string, number | null> = {};
			for (const kw of knownWordsData) {
				kwMap[kw.word] = kw.familiarity;
			}
			knownWords = kwMap;

			garbageWords = new Set(
				garbageData.filter((g: any) => !g.is_override).map((g: any) => g.word)
			);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load analysis';
		} finally {
			loading = false;
		}
	});

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

	async function markAsGarbage(word: string) {
		try {
			await api.createGarbageWord(word);
			garbageWords = new Set([...garbageWords, word]);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to mark as garbage';
		}
	}

	async function openWordDetail(word: string) {
		loadingDetail = true;
		selectedWord = null;
		try {
			selectedWord = await api.getWordDetail(word) as WordDetail;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load word detail';
		} finally {
			loadingDetail = false;
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
</script>

<div class="min-h-screen bg-gray-50">
	<nav class="bg-white shadow-sm px-6 py-4 flex justify-between items-center">
		<div class="flex items-center gap-4">
			<a href="/" class="text-gray-600 hover:text-gray-800 text-sm">← Back</a>
			<h1 class="text-xl font-bold text-gray-800">
				{analysis?.title ?? 'Analysis Results'}
			</h1>
		</div>
		{#if analysis}
			<div class="text-sm text-gray-500 flex gap-4">
				<span>{analysis.unique_words} unique words</span>
				<span>{analysis.total_words} total occurrences</span>
			</div>
		{/if}
	</nav>

	<main class="max-w-5xl mx-auto px-6 py-8">
		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		<!-- Filters -->
		<div class="bg-white rounded-lg shadow-sm p-4 mb-4 flex flex-wrap gap-4 items-center">
			<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
				<input
					type="checkbox"
					bind:checked={hideNonChinese}
					class="rounded"
				/>
				Hide non-Chinese characters
			</label>

			{#if supplementalCount() > 0}
				<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
					<input
						type="checkbox"
						bind:checked={hideSupplemental}
						class="rounded"
					/>
					Hide extra matches ({supplementalCount()})
				</label>
			{/if}

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

			<span class="text-sm text-gray-400">
				Showing {filteredResults().length} of {analysis?.results.length ?? 0} words
			</span>
		</div>

		<div class="flex gap-4">
			<!-- Results table -->
			<div class="flex-1 bg-white rounded-lg shadow-sm overflow-hidden">
				{#if loading}
					<p class="text-gray-500 p-4">Loading...</p>
				{:else if analysis}
					<table class="w-full">
						<thead class="bg-gray-50 border-b border-gray-200">
							<tr>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Word</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Count</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Source</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Familiarity</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Mark as</th>
								<th class="text-left px-4 py-3 text-sm font-medium text-gray-700">Actions</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-gray-100">
							{#each filteredResults() as result}
								<tr class="hover:bg-gray-50 {result.source === 'longest_match_only' ? 'bg-amber-50/40' : ''}">
									<td class="px-4 py-3 text-lg font-medium">{result.word}</td>
									<td class="px-4 py-3 text-gray-600">{result.count}</td>
									<td class="px-4 py-3">
										<span
											class="text-xs px-2 py-1 rounded-full {sourceColor(result.source)}"
											title={result.source === 'longest_match_only' ? 'Found only by the legacy longest-matching pass — not confirmed by the main segmenter. Likely a dictionary gap; review before trusting it.' : ''}
										>
											{sourceLabel(result.source)}
										</span>
									</td>
									<td class="px-4 py-3">
										<span class="text-xs px-2 py-1 rounded-full {familiarityColor(currentFamiliarity(result))}">
											{familiarityLabel(currentFamiliarity(result))}
										</span>
									</td>
									<td class="px-4 py-3">
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
									</td>
									<td class="px-4 py-3">
										<div class="flex gap-2">
											<button
												onclick={() => openWordDetail(result.word)}
												class="text-xs text-blue-600 hover:text-blue-800"
												title="View details"
											>
												Info
											</button>
											<button
												onclick={() => markAsGarbage(result.word)}
												class="text-xs text-red-400 hover:text-red-600"
												title="Mark as garbage"
											>
												Trash
											</button>
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>

			<!-- Word detail panel -->
			{#if selectedWord || loadingDetail}
				<div class="w-72 bg-white rounded-lg shadow-sm p-4 self-start sticky top-4">
					{#if loadingDetail}
						<p class="text-gray-500 text-sm">Loading...</p>
					{:else if selectedWord}
						<div class="flex justify-between items-start mb-3">
							<h2 class="text-3xl font-medium">{selectedWord.word}</h2>
							<button
								onclick={() => selectedWord = null}
								class="text-gray-400 hover:text-gray-600"
							>✕</button>
						</div>

						<!-- HSK levels -->
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

						<!-- Frequency -->
						{#if selectedWord.frequency}
							<p class="text-xs text-gray-500 mb-3">
								Corpus frequency: {selectedWord.frequency.toLocaleString()}
							</p>
						{/if}

						<!-- Forms -->
						{#if selectedWord.forms.length > 0}
							<div class="space-y-3">
								{#each selectedWord.forms as form, i}
									<div class="border-t border-gray-100 pt-3">
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
						{:else}
							<p class="text-sm text-gray-400">No dictionary entry found for this word.</p>
						{/if}
					{/if}
				</div>
			{/if}
		</div>
	</main>
</div>