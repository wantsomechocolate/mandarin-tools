<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn, logout } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import AccountMenu from '$lib/components/AccountMenu.svelte';
	import { getThemePreference, setThemePreference, type ThemePreference } from '$lib/theme.svelte';
	import {
		getSectionDefaults,
		setSectionDefault,
		SECTION_ORDER,
		SECTION_LABELS,
		type PanelSectionId,
	} from '$lib/sectionVisibilityPersistence';
	import { getContextChars, setContextChars, MIN_CONTEXT_CHARS, MAX_CONTEXT_CHARS } from '$lib/contextPreferences';
	import { loadExportPreferences, saveExportPreferences, type ExportPreferences } from '$lib/exportPreferences';
	import {
		loadRepeatedSequencePreferences,
		saveRepeatedSequencePreferences,
		type RepeatedSequencePreferences,
	} from '$lib/repeatedSequencePreferences';

	// The Account page - username/email/member-since, change password,
	// delete account. Deliberately NOT the vocabulary-management section
	// this app used to call "Profile" (see routes/word-lists/+layout.svelte's
	// own docstring for that rename) - "Profile" now means what it means
	// everywhere else: your own account identity/security, not a list of
	// words. A standalone page, not a tabbed section like Word Lists - one
	// page's worth of content, no reason to split it into tabs.

	interface CurrentUser {
		id: number;
		email: string;
		username: string;
		is_active: boolean;
		created_at: string;
	}

	let user: CurrentUser | null = $state(null);
	let loading = $state(true);
	let loadError = $state('');

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			user = await api.getCurrentUser() as CurrentUser;
		} catch (e: unknown) {
			loadError = e instanceof Error ? e.message : 'Failed to load account';
		} finally {
			loading = false;
		}
		try {
			exportPrefs = await loadExportPreferences();
		} catch {
			// Non-fatal - the Export card just stays in its loading state;
			// every other card on this page already loaded independently.
		}
		try {
			repeatedSequencePrefs = await loadRepeatedSequencePreferences();
		} catch {
			// Non-fatal, same reasoning as the Export card above.
		}
	});

	// Export (Pleco) - backend-persisted (see exportPreferences.ts's own
	// docstring for why this, unlike every other preference on this page,
	// isn't localStorage). Every toggle saves immediately on change, same
	// "no separate Save button" pattern the Preferences card below already
	// uses for theme/section defaults.
	let exportPrefs: ExportPreferences | null = $state(null);

	function updateExportPrefs(next: ExportPreferences) {
		exportPrefs = next;
		saveExportPreferences(next);
	}

	function toggleIncludePinyin() {
		if (!exportPrefs) return;
		updateExportPrefs({ ...exportPrefs, includePinyin: !exportPrefs.includePinyin });
	}

	function toggleIncludeDefinitions() {
		if (!exportPrefs) return;
		updateExportPrefs({ ...exportPrefs, includeDefinitions: !exportPrefs.includeDefinitions });
	}

	function toggleDefinitionSource(source: keyof ExportPreferences['definitionSources']) {
		if (!exportPrefs) return;
		updateExportPrefs({
			...exportPrefs,
			definitionSources: { ...exportPrefs.definitionSources, [source]: !exportPrefs.definitionSources[source] },
		});
	}

	// The four "additional info" toggles (Familiarity/Sample sentences/
	// Context/Global note) - not "word definition" content the way
	// definitionSources is, so they're their own flat group, same generic
	// keyof pattern as toggleDefinitionSource above.
	function toggleAdditionalInfo(
		key: 'includeFamiliarity' | 'includeSampleSentences' | 'includeContext' | 'includeGlobalNote'
	) {
		if (!exportPrefs) return;
		updateExportPrefs({ ...exportPrefs, [key]: !exportPrefs[key] });
	}

	// Advanced - the repeated-sequence tokenizer's minimum word length/count
	// thresholds (see repeatedSequencePreferences.ts's own docstring for why
	// these are an account-wide default rather than a per-analysis option).
	// Backend-persisted like Export above, not localStorage - same
	// immediate-save-on-change pattern, applied to every analysis run from
	// here on (not retroactively to analyses already run).
	let repeatedSequencePrefs: RepeatedSequencePreferences | null = $state(null);

	function updateRepeatedSequencePrefs(next: RepeatedSequencePreferences) {
		repeatedSequencePrefs = next;
		saveRepeatedSequencePreferences(next);
	}

	function updateMinTokenLength(value: number) {
		if (!repeatedSequencePrefs || !Number.isFinite(value)) return;
		updateRepeatedSequencePrefs({ ...repeatedSequencePrefs, minTokenLength: Math.max(1, Math.round(value)) });
	}

	function updateMinTokenCount(value: number) {
		if (!repeatedSequencePrefs || !Number.isFinite(value)) return;
		updateRepeatedSequencePrefs({ ...repeatedSequencePrefs, minTokenCount: Math.max(1, Math.round(value)) });
	}

	// Preferences - theme (moved here from AccountMenu's dropdown, which
	// still carries its own copy too - both just read/write the same
	// module-level state in theme.svelte.ts, so there's no separate source
	// of truth to keep in sync, just two controls on the same value) and
	// the global default collapsed/expanded state for each of
	// WordDetailPanel.svelte's 8 sections (see sectionVisibilityPersistence.ts's
	// docstring for how a specific word's own overrides take priority over
	// these once the user's actually touched a section for that word).
	let sectionDefaults = $state(getSectionDefaults());
	function toggleSectionDefault(section: PanelSectionId) {
		const next = !sectionDefaults[section];
		sectionDefaults = { ...sectionDefaults, [section]: next };
		setSectionDefault(section, next);
	}

	// How much surrounding text a word's Context (results-row/card accordion,
	// and WordDetailPanel's own Context section) shows on each side of a
	// match - see contextPreferences.ts's own docstring. Already-fetched/
	// cached context elsewhere in the app won't retroactively pick up a
	// change made here (same as every other preference on this page) - a
	// fresh fetch is what applies it, which a reload or reopening a word's
	// panel/row already naturally triggers.
	let contextChars = $state(getContextChars());
	function updateContextChars(value: number) {
		if (!Number.isFinite(value)) return;
		setContextChars(value);
		contextChars = getContextChars(); // re-read the clamped value, not necessarily what was typed
	}

	// Change password
	let currentPassword = $state('');
	let newPassword = $state('');
	let confirmPassword = $state('');
	let changingPassword = $state(false);
	let passwordError = $state('');
	let passwordSuccess = $state(false);

	const passwordMismatch = $derived(
		confirmPassword !== '' && newPassword !== confirmPassword
	);

	async function submitPasswordChange() {
		passwordError = '';
		passwordSuccess = false;
		if (!currentPassword || !newPassword) return;
		if (newPassword !== confirmPassword) {
			passwordError = 'New password and confirmation do not match.';
			return;
		}
		changingPassword = true;
		try {
			await api.changePassword(currentPassword, newPassword);
			passwordSuccess = true;
			currentPassword = '';
			newPassword = '';
			confirmPassword = '';
		} catch (e: unknown) {
			passwordError = e instanceof Error ? e.message : 'Failed to change password';
		} finally {
			changingPassword = false;
		}
	}

	// Delete account - the one genuinely irreversible action in this app
	// (destroys every table of user-owned data, see
	// service.delete_user_account's docstring, router.py) - gated on
	// re-entering the current password (not just a click-through confirm,
	// unlike the app's one other destructive action - deleting an input
	// text, +page.svelte - which is reversible in spirit, since only that
	// one text is lost, not the whole account) rather than a native
	// confirm(), since there's a real value (the password) to collect, not
	// just a yes/no.
	let deletePassword = $state('');
	let deleting = $state(false);
	let deleteError = $state('');

	async function submitDeleteAccount() {
		deleteError = '';
		if (!deletePassword) return;
		deleting = true;
		try {
			await api.deleteAccount(deletePassword);
			logout();
		} catch (e: unknown) {
			deleteError = e instanceof Error ? e.message : 'Failed to delete account';
			deleting = false;
		}
	}
</script>

{#snippet iconHome()}
	<svg class="w-8 h-8 block" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 9.5L10 4l6.5 5.5" />
		<path d="M5 8.5v7.75a0.25 0.25 0 0 0 0.25 0.25h9.5a0.25 0.25 0 0 0 0.25-0.25v-7.75" />
	</svg>
{/snippet}

<svelte:head><title>Account - Mandarin Tools</title></svelte:head>

<div class="min-h-screen bg-gray-50 dark:bg-slate-950">
	<nav class="bg-white dark:bg-slate-900 shadow-sm px-6 py-4 flex items-center justify-between gap-4">
		<div class="flex items-center gap-4">
			<a href="/" class="text-gray-600 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400" aria-label="Home" title="Home">
				{@render iconHome()}
			</a>
			<h1 class="text-xl font-bold text-gray-800 dark:text-slate-200">Account</h1>
		</div>
		<AccountMenu />
	</nav>

	<main class="max-w-2xl mx-auto px-6 py-8">
		{#if loadError}
			<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-4 py-3 rounded mb-4">
				{loadError}
			</div>
		{/if}

		{#if loading}
			<p class="text-gray-500 dark:text-slate-400">Loading...</p>
		{:else if user}
			<!-- Identity - read-only. Editing username/email raises its own
			     questions (uniqueness checks, whether an email change needs
			     re-verification) deliberately left for a later pass, not built
			     into this one - see the plan this page came from. -->
			<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6 mb-6">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-slate-300 mb-4">Account details</h2>
				<dl class="space-y-3 text-sm">
					<div class="flex justify-between">
						<dt class="text-gray-500 dark:text-slate-400">Username</dt>
						<dd class="text-gray-800 dark:text-slate-200 font-medium">{user.username}</dd>
					</div>
					<div class="flex justify-between">
						<dt class="text-gray-500 dark:text-slate-400">Email</dt>
						<dd class="text-gray-800 dark:text-slate-200 font-medium">{user.email}</dd>
					</div>
					<div class="flex justify-between">
						<dt class="text-gray-500 dark:text-slate-400">Member since</dt>
						<dd class="text-gray-800 dark:text-slate-200 font-medium">{new Date(user.created_at).toLocaleDateString()}</dd>
					</div>
				</dl>
			</div>

			<!-- Preferences - theme, and the word-detail panel's per-section
			     show/hide defaults. Both are plain localStorage preferences
			     (see theme.svelte.ts / sectionVisibilityPersistence.ts), not
			     account data from the server - this card is just the one
			     discoverable place to see/change them all, not a different
			     storage mechanism than what was already there. -->
			<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6 mb-6">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-slate-300 mb-4">Preferences</h2>

				<!-- Theme - System/Light/Dark, not a two-way toggle, same
				     reasoning as the identical control in AccountMenu's dropdown
				     (see its own docstring) - this is a second control on that
				     same underlying preference, not a separate copy of it, so
				     changing it here or there always agrees. -->
				<div class="mb-5">
					<label for="theme-select-prefs" class="block text-xs text-gray-500 dark:text-slate-400 mb-1">Theme</label>
					<select
						id="theme-select-prefs"
						value={getThemePreference()}
						onchange={(e) => setThemePreference(e.currentTarget.value as ThemePreference)}
						class="w-full max-w-xs text-sm border border-gray-300 rounded px-2 py-1.5 bg-white text-gray-700 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-200"
					>
						<option value="system">System</option>
						<option value="light">Light</option>
						<option value="dark">Dark</option>
					</select>
				</div>

				<!-- Word detail panel sections - the default a section opens in
				     (shown/collapsed) the first time a given word's panel shows
				     it. A word you've actually toggled a section on/off for
				     remembers that instead, forever, regardless of what these
				     defaults later change to - see sectionVisibilityPersistence.ts's
				     own docstring for that resolution. -->
				<div>
					<span class="block text-xs text-gray-500 dark:text-slate-400 mb-1.5">
						Word detail panel sections - shown by default
					</span>
					<p class="text-xs text-gray-400 dark:text-slate-500 mb-2">
						Only affects a word's panel the first time you view it - a section you've
						manually shown or hidden for a specific word stays that way from then on.
					</p>
					<div class="space-y-1.5">
						{#each SECTION_ORDER as section (section)}
							<label class="flex items-center gap-2 text-sm text-gray-700 dark:text-slate-300">
								<input
									type="checkbox"
									checked={!sectionDefaults[section]}
									onchange={() => toggleSectionDefault(section)}
									class="rounded border-gray-300"
								/>
								{SECTION_LABELS[section]}
							</label>
						{/each}
					</div>
				</div>

				<!-- Context length - how many characters of surrounding text a word's
				     Context shows on each side of a match, wherever it's shown
				     (results-row/card accordion, and the panel's own Context
				     section). Same "applies to fresh fetches only" caveat as every
				     other preference here - see contextChars' own docstring above. -->
				<div class="mt-5 pt-4 border-t border-gray-100 dark:border-slate-800">
					<label for="context-chars" class="block text-xs text-gray-500 dark:text-slate-400 mb-1.5">
						Context length - characters shown on each side of a match
					</label>
					<div class="flex items-center gap-3 max-w-xs">
						<input
							id="context-chars"
							type="range"
							min={MIN_CONTEXT_CHARS}
							max={MAX_CONTEXT_CHARS}
							value={contextChars}
							oninput={(e) => updateContextChars(Number(e.currentTarget.value))}
							class="flex-1"
						/>
						<span class="text-sm text-gray-700 dark:text-slate-300 w-8 text-right tabular-nums">{contextChars}</span>
					</div>
				</div>
			</div>

			<!-- Export - the account-level settings ExportDialog.svelte
			     (analyze/[id]/+page.svelte) reads at export time, shared by
			     both the Pleco and Excel formats. Only "respect the current
			     filter or not" (and which format) stay export-time decisions
			     in that dialog - everything else lives here so an export is a
			     two-click "download" rather than a form to fill out every
			     time. Backend-persisted (see exportPreferences.ts), unlike the
			     Preferences card below - every toggle here saves immediately,
			     same as that card's own immediate-apply pattern. -->
			<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6 mb-6">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-slate-300 mb-4">Export</h2>
				{#if !exportPrefs}
					<p class="text-xs text-gray-400 dark:text-slate-500">Loading…</p>
				{:else}
					<div class="space-y-3">
						<!-- Pleco-only: it's the dedicated 2nd tab-separated field a
						     Pleco card has, resolved via the backend's HSK -> CC-CEDICT
						     -> UserWord -> auto-generated fallback chain (ExportWordData.
						     pinyin). The .xlsx template has no equivalent standalone
						     Pinyin column - pinyin there only ever shows up inline,
						     per-form/sense/entry, inside HSK/CC-CEDICT/User/Auto-Generated's
						     own cells, gated by those columns' own toggles instead. -->
						<label class="flex items-center gap-2 text-sm text-gray-700 dark:text-slate-300">
							<input type="checkbox" checked={exportPrefs.includePinyin} onchange={toggleIncludePinyin} class="rounded border-gray-300" />
							Include pinyin <span class="text-gray-400 dark:text-slate-500">(Pleco only)</span>
						</label>
						<div>
							<label class="flex items-center gap-2 text-sm text-gray-700 dark:text-slate-300">
								<input type="checkbox" checked={exportPrefs.includeDefinitions} onchange={toggleIncludeDefinitions} class="rounded border-gray-300" />
								Include definitions
							</label>
							{#if exportPrefs.includeDefinitions}
								<div class="mt-2 ml-6 space-y-1.5">
									<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
										<input type="checkbox" checked={exportPrefs.definitionSources.corpusFrequency} onchange={() => toggleDefinitionSource('corpusFrequency')} class="rounded border-gray-300" />
										Corpus frequency
									</label>
									<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
										<input type="checkbox" checked={exportPrefs.definitionSources.hsk} onchange={() => toggleDefinitionSource('hsk')} class="rounded border-gray-300" />
										HSK
									</label>
									<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
										<input type="checkbox" checked={exportPrefs.definitionSources.cedict} onchange={() => toggleDefinitionSource('cedict')} class="rounded border-gray-300" />
										CC-CEDICT
									</label>
									<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
										<input type="checkbox" checked={exportPrefs.definitionSources.autoGenerated} onchange={() => toggleDefinitionSource('autoGenerated')} class="rounded border-gray-300" />
										Auto-generated
									</label>
									<div class="pt-1.5">
										<span class="block text-xs text-gray-500 dark:text-slate-400 mb-1">Your definitions</span>
										<div class="space-y-1.5">
											<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
												<input type="checkbox" checked={exportPrefs.definitionSources.userGlobal} onchange={() => toggleDefinitionSource('userGlobal')} class="rounded border-gray-300" />
												Global entries
											</label>
											<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
												<input type="checkbox" checked={exportPrefs.definitionSources.userText} onchange={() => toggleDefinitionSource('userText')} class="rounded border-gray-300" />
												Text-specific entries
											</label>
											<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
												<input type="checkbox" checked={exportPrefs.definitionSources.userAnalysis} onchange={() => toggleDefinitionSource('userAnalysis')} class="rounded border-gray-300" />
												Analysis-specific entries
											</label>
										</div>
									</div>
								</div>
							{/if}
						</div>

						<!-- Additional info - not "word definition" content the way
						     definitionSources above is (a count/score/sentence list/
						     note, not a source of meaning), so it's its own flat
						     group, independent of "Include definitions". -->
						<div class="pt-2 border-t border-gray-100 dark:border-slate-800">
							<span class="block text-xs text-gray-500 dark:text-slate-400 mb-1.5">Additional info</span>
							<div class="space-y-1.5">
								<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
									<input type="checkbox" checked={exportPrefs.includeFamiliarity} onchange={() => toggleAdditionalInfo('includeFamiliarity')} class="rounded border-gray-300" />
									Familiarity score
								</label>
								<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
									<input type="checkbox" checked={exportPrefs.includeSampleSentences} onchange={() => toggleAdditionalInfo('includeSampleSentences')} class="rounded border-gray-300" />
									Sample sentences
								</label>
								<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
									<input type="checkbox" checked={exportPrefs.includeContext} onchange={() => toggleAdditionalInfo('includeContext')} class="rounded border-gray-300" />
									Context
								</label>
								<label class="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400">
									<input type="checkbox" checked={exportPrefs.includeGlobalNote} onchange={() => toggleAdditionalInfo('includeGlobalNote')} class="rounded border-gray-300" />
									Global note
								</label>
							</div>
						</div>
					</div>
				{/if}
			</div>

			<!-- Advanced - repeated-sequence detection thresholds. A separate
			     card from Preferences above (not backend-persisted the same
			     way) and Export (a different feature entirely) - grouped here
			     as "Advanced" since these are tuning knobs for a specific
			     algorithm's sensitivity, not general app preferences. -->
			<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6 mb-6">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-slate-300 mb-1">Advanced</h2>
				<p class="text-xs text-gray-400 dark:text-slate-500 mb-4">
					Applies to new analyses only - re-run a text's analysis to pick up a change here.
				</p>
				{#if !repeatedSequencePrefs}
					<p class="text-xs text-gray-400 dark:text-slate-500">Loading…</p>
				{:else}
					<div>
						<span class="block text-xs text-gray-500 dark:text-slate-400 mb-1.5">
							Repeated sequence detection
						</span>
						<p class="text-xs text-gray-400 dark:text-slate-500 mb-2">
							Controls which repeated runs of unrecognized characters get flagged for review.
						</p>
						<div class="flex flex-wrap gap-4">
							<div>
								<label for="min-token-length" class="block text-xs text-gray-500 dark:text-slate-400 mb-1">
									Minimum word length
								</label>
								<input
									id="min-token-length"
									type="number"
									min="1"
									step="1"
									value={repeatedSequencePrefs.minTokenLength}
									onchange={(e) => updateMinTokenLength(Number(e.currentTarget.value))}
									class="w-20 border border-gray-300 rounded px-2 py-1.5 text-sm bg-white text-gray-700 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-200"
								/>
							</div>
							<div>
								<label for="min-token-count" class="block text-xs text-gray-500 dark:text-slate-400 mb-1">
									Minimum count
								</label>
								<input
									id="min-token-count"
									type="number"
									min="1"
									step="1"
									value={repeatedSequencePrefs.minTokenCount}
									onchange={(e) => updateMinTokenCount(Number(e.currentTarget.value))}
									class="w-20 border border-gray-300 rounded px-2 py-1.5 text-sm bg-white text-gray-700 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-200"
								/>
							</div>
						</div>
					</div>
				{/if}
			</div>

			<!-- Change password -->
			<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6 mb-6">
				<h2 class="text-sm font-semibold text-gray-700 dark:text-slate-300 mb-4">Change password</h2>
				{#if passwordError}
					<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-3 py-2 rounded text-sm mb-3">
						{passwordError}
					</div>
				{/if}
				{#if passwordSuccess}
					<div class="bg-emerald-50 border border-emerald-200 text-emerald-700 px-3 py-2 rounded text-sm mb-3">
						Password changed.
					</div>
				{/if}
				<div class="space-y-3">
					<div>
						<label for="current-password" class="block text-xs text-gray-500 dark:text-slate-400 mb-1">Current password</label>
						<input
							id="current-password"
							type="password"
							bind:value={currentPassword}
							class="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
						/>
					</div>
					<div>
						<label for="new-password" class="block text-xs text-gray-500 dark:text-slate-400 mb-1">New password</label>
						<input
							id="new-password"
							type="password"
							bind:value={newPassword}
							class="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
						/>
					</div>
					<div>
						<label for="confirm-password" class="block text-xs text-gray-500 dark:text-slate-400 mb-1">Confirm new password</label>
						<input
							id="confirm-password"
							type="password"
							bind:value={confirmPassword}
							class="w-full border border-gray-300 rounded px-2 py-1.5 text-sm {passwordMismatch ? 'border-red-300 dark:border-red-500/40' : ''}"
							onkeydown={(e) => { if (e.key === 'Enter') submitPasswordChange(); }}
						/>
						{#if passwordMismatch}
							<p class="text-xs text-red-600 dark:text-red-400 mt-1">Passwords do not match.</p>
						{/if}
					</div>
					<button
						onclick={submitPasswordChange}
						disabled={!currentPassword || !newPassword || !confirmPassword || passwordMismatch || changingPassword}
						class="text-sm px-4 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50"
					>
						{changingPassword ? 'Changing...' : 'Change password'}
					</button>
				</div>
			</div>

			<!-- Danger zone - visually distinct (red border/heading) from
			     everything else on the page, matching the convention that this
			     is a different category of action, not just another form. -->
			<div class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-6 border-2 border-red-200 dark:border-red-500/30">
				<h2 class="text-sm font-semibold text-red-700 dark:text-red-400 mb-1">Delete account</h2>
				<p class="text-xs text-gray-500 dark:text-slate-400 mb-4">
					Permanently deletes your account and everything tied to it - every text, analysis,
					known/user/starred word, note, and stopword/garbage-word customization. This cannot
					be undone.
				</p>
				{#if deleteError}
					<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-3 py-2 rounded text-sm mb-3">
						{deleteError}
					</div>
				{/if}
				<div class="flex flex-wrap items-end gap-2">
					<div>
						<label for="delete-password" class="block text-xs text-gray-500 dark:text-slate-400 mb-1">Enter your password to confirm</label>
						<input
							id="delete-password"
							type="password"
							bind:value={deletePassword}
							class="border border-gray-300 rounded px-2 py-1.5 text-sm w-56"
							onkeydown={(e) => { if (e.key === 'Enter') submitDeleteAccount(); }}
						/>
					</div>
					<button
						onclick={submitDeleteAccount}
						disabled={!deletePassword || deleting}
						class="text-sm px-4 py-1.5 bg-red-600 dark:bg-red-500 text-white rounded hover:bg-red-700 dark:hover:bg-red-600 disabled:opacity-50"
					>
						{deleting ? 'Deleting...' : 'Delete my account'}
					</button>
				</div>
			</div>
		{/if}
	</main>
</div>
