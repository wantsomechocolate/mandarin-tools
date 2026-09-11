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
	});

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
	<svg class="w-8 h-8" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 9.5L10 4l6.5 5.5" />
		<path d="M5 8.5v7a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-7" />
		<path d="M8 16.5v-4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v4" />
	</svg>
{/snippet}

<svelte:head><title>Account - Mandarin Tools</title></svelte:head>

<div class="min-h-screen bg-gray-50 dark:bg-slate-950">
	<nav class="bg-white dark:bg-slate-900 shadow-sm px-6 py-4 flex items-center justify-between gap-4">
		<div class="flex items-center gap-4">
			<a href="/" class="text-gray-400 dark:text-slate-500 hover:text-blue-600 dark:hover:text-blue-400" aria-label="Home" title="Home">
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
